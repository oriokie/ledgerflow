"""Read models over income: what you expect, what you got, and what is left.

Three disciplines are inherited from the rest of the product and are not
negotiable here.

**Single currency.** Like ``net_worth``, ``cashflow_statement`` and the
cash-flow calendar, nothing here sums across currencies. Income is reported per
currency and the caller is told which one, because a household paid partly in
KES and partly in USD has two incomes, not one number.

**Absence is not zero.** Every figure that cannot be computed returns ``None``,
never ``0``. "This user has no recorded income" and "this user earns nothing"
are different facts and a household will act differently on each. The same rule
the goal forecast applies to ``success_probability`` applies to every ratio
below.

**A measured figure beats a typed one.** For a ``VARIABLE`` or ``IRREGULAR``
source the user's stated amount is a guess about their own future. Where enough
receipts exist, the expected amount is the *observed mean* and the stated figure
is demoted to a fallback. This is the point of recording receipts at all.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from django.utils import timezone

from apps.finance.models import Bill, BillStatus, RecurringTransaction, RecurringType
from apps.finance.schedule import amount_in_month, first_month_day_on_or_after, iter_occurrences

from .models import (
    INCOME_DAY_OF_MONTH_CADENCES,
    INCOME_SCHEDULE_UNIT,
    PAYMENTS_PER_YEAR,
    IncomeDeduction,
    IncomeFrequency,
    IncomeReceipt,
    IncomeSource,
    Reliability,
)

#: Receipts needed before observed history overrides the user's stated amount.
#: Three is the smallest number from which a mean is not simply the last value
#: wearing a disguise, and below it `statistics.stdev` is undefined anyway.
MIN_RECEIPTS_FOR_OBSERVED = 3

#: How far back a receipt still counts toward the observed mean. A year covers
#: seasonal trades without letting a job someone left two years ago hold down
#: the average of the one they have now.
OBSERVED_WINDOW_DAYS = 365


def monthly_equivalent_minor(amount_minor: int, frequency: str) -> int | None:
    """One payment at a cadence -> what it averages per month.

    ``None`` for ``AD_HOC``: money that arrives whenever it arrives has no
    monthly equivalent, and inventing one is exactly the confident-figure-from-
    nothing this product refuses elsewhere.

    Note the arithmetic runs through *payments per year*, not through "weeks in
    a month". Fortnightly pay is 26 payments a year, which is 2.167 a month,
    not 2 — the naive version loses a fortnight's pay annually.
    """
    per_year = PAYMENTS_PER_YEAR.get(frequency)
    if per_year is None:
        return None
    return round(amount_minor * per_year / 12)


@dataclass(frozen=True, slots=True)
class SourceView:
    """One income source with its observed history folded in."""

    source_id: str
    name: str
    kind: str
    payer: str
    currency: str
    frequency: str
    reliability: str
    is_active: bool
    starts_on: date
    ends_on: date | None
    #: True when `as_of` sits inside [starts_on, ends_on]. A source that has
    #: ended (or not yet started) stays on the list so it can be edited, but
    #: it must not feed this month's income, committed-income ratio, or
    #: envelope — that is how a finished contract quietly inflates every plan.
    is_current: bool

    #: What the user said one payment is worth.
    stated_net_minor: int
    stated_gross_minor: int | None

    #: What payments have actually been worth, when there are enough to say.
    observed_mean_minor: int | None
    observed_stdev_minor: int | None
    receipt_count: int
    last_received_on: date | None

    #: The figure to plan with: observed where it exists, stated otherwise.
    expected_net_minor: int
    #: True when `expected_net_minor` came from receipts rather than the form.
    expected_is_observed: bool

    #: Monthly equivalent of `expected_net_minor`. `None` for ad-hoc cadence.
    monthly_net_minor: int | None
    deductions_minor: int | None
    #: First payday on or after `starts_on`. Periodical projections count from
    #: this date, not from the day the source was recorded.
    anchor: date

    @property
    def is_speculative(self) -> bool:
        """Whether a figure from this source may be drawn as a bare numeral.

        An irregular source with no history behind it is a hope. The UI must
        render it as speculative and attach its confidence statement, exactly
        as it would for any other model output on thin data.
        """
        return self.reliability == Reliability.IRREGULAR and not self.expected_is_observed

    @property
    def variance_pct(self) -> float | None:
        """Spread of actual payments as a share of their mean.

        The single most useful number about a variable income and the one no
        form can supply. `None` unless there is enough history to mean it.
        """
        if self.observed_mean_minor is None or self.observed_stdev_minor is None:
            return None
        if self.observed_mean_minor <= 0:
            return None
        return round(self.observed_stdev_minor / self.observed_mean_minor * 100, 1)


def deductions_for(source: IncomeSource) -> int | None:
    """Total withheld per payment, or ``None`` when it cannot be known.

    Percentage deductions are a share of **gross**, so a source with no gross
    on file cannot resolve them. Returning 0 in that case would report a
    take-home rate of 100% for someone who is taxed — the most misleading
    single number this module could produce. `None` makes the caller say "not
    known" instead.
    """
    lines = list(IncomeDeduction.objects.filter(source=source))
    if not lines:
        return 0 if source.gross_minor is None else max(0, source.gross_minor - source.net_minor)

    if any(line.percent_bp is not None for line in lines) and source.gross_minor is None:
        return None

    total = 0
    for line in lines:
        if line.amount_minor is not None:
            total += line.amount_minor
        else:
            total += round((source.gross_minor or 0) * line.percent_bp / 10000)
    return total


def _observed(source: IncomeSource, *, as_of: date) -> tuple[int | None, int | None, int, date | None]:
    """Mean, standard deviation, count and latest date of recent receipts."""
    window_start = as_of - timedelta(days=OBSERVED_WINDOW_DAYS)
    amounts = list(
        IncomeReceipt.objects.filter(source=source, occurred_on__gte=window_start, occurred_on__lte=as_of)
        .order_by("-occurred_on")
        .values_list("net_minor", "occurred_on")
    )
    if not amounts:
        return None, None, 0, None

    values = [a for a, _ in amounts]
    last_on = amounts[0][1]
    if len(values) < MIN_RECEIPTS_FOR_OBSERVED:
        # Not enough to characterise, but the count and the last date are still
        # facts worth returning — "you were last paid on the 3rd" needs one
        # receipt, not three.
        return None, None, len(values), last_on

    return round(statistics.fmean(values)), round(statistics.stdev(values)), len(values), last_on


def occurrence_anchor(source: IncomeSource) -> date:
    """The date series this source is counted from.

    A numbered pay day beats `starts_on`'s day-of-month so a salary recorded
    on the 16th still lands on the 25th — the same rule the cash-flow calendar
    uses, so projections and analytics cannot disagree about which month the
    block belongs to.
    """
    if source.pay_day and source.frequency in INCOME_DAY_OF_MONTH_CADENCES:
        return first_month_day_on_or_after(source.starts_on, day=source.pay_day)
    return source.starts_on


def iter_income_paydays(source: IncomeSource, *, start: date, end: date):
    """Yield the dates this source is expected to pay inside `[start, end]`.

    Semi-monthly is two monthly series. A numbered pay day beats `starts_on`'s
    day-of-month so a salary recorded on the 16th still lands on the 25th.
    """
    if source.frequency == IncomeFrequency.AD_HOC:
        return
    window_start = max(start, source.starts_on)
    window_end = end if source.ends_on is None else min(end, source.ends_on)
    if window_start > window_end:
        return

    if source.frequency == IncomeFrequency.SEMI_MONTHLY:
        for day in (source.pay_day, source.second_pay_day):
            if day is None:
                continue
            yield from iter_occurrences(
                anchor=first_month_day_on_or_after(source.starts_on, day=day),
                frequency="monthly",
                interval=1,
                start=window_start,
                end=window_end,
                ends_on=source.ends_on,
            )
        return

    unit = INCOME_SCHEDULE_UNIT.get(source.frequency)
    if unit is None:
        return
    freq, interval = unit
    yield from iter_occurrences(
        anchor=occurrence_anchor(source),
        frequency=freq,
        interval=interval,
        start=window_start,
        end=window_end,
        ends_on=source.ends_on,
    )


def _expected_payment_minor(source: IncomeSource, *, as_of: date) -> int | None:
    """Amount the calendar would place on payday, or ``None`` to skip."""
    mean, _stdev, _count, _last = _observed(source, as_of=as_of)
    use_observed = mean is not None and source.reliability != Reliability.FIXED
    if source.reliability == Reliability.IRREGULAR and not use_observed:
        return None
    expected = mean if use_observed else source.net_minor
    if expected <= 0:
        return None
    return expected


def scheduled_income_minor(*, currency: str, start: date, end: date) -> int:
    """Unlinked IncomeSource payments expected in ``[start, end]``.

    Linked posting templates already appear as transactions (or calendar
    recurring events). Callers that must not invent the past pass *today* as
    ``start``: a payday that came and went without posting is a miss, not
    income.
    """
    if start > end:
        return 0
    total = 0
    sources = IncomeSource.objects.filter(
        is_active=True,
        currency=currency,
        recurring_transaction__isnull=True,
    )
    for source in sources:
        expected = _expected_payment_minor(source, as_of=end)
        if expected is None:
            continue
        for _occurs in iter_income_paydays(source, start=start, end=end):
            total += expected
    return total


def source_views(*, as_of: date | None = None, currency: str | None = None) -> list[SourceView]:
    """Every active source, with observation folded into expectation."""
    as_of = as_of or timezone.localdate()
    queryset = IncomeSource.objects.filter(is_active=True)
    if currency:
        queryset = queryset.filter(currency=currency)

    views: list[SourceView] = []
    for source in queryset.order_by("name"):
        mean, stdev, count, last_on = _observed(source, as_of=as_of)

        # A fixed source keeps its stated amount even with history behind it:
        # a salaried user who got one bonus should not have their salary
        # permanently restated upward by it. Observation overrides expectation
        # only where the arrangement was never fixed in the first place.
        use_observed = mean is not None and source.reliability != Reliability.FIXED
        expected = mean if use_observed else source.net_minor

        views.append(
            SourceView(
                source_id=str(source.id),
                name=source.name,
                kind=source.kind,
                payer=source.payer,
                currency=source.currency,
                frequency=source.frequency,
                reliability=source.reliability,
                is_active=source.is_active,
                starts_on=source.starts_on,
                ends_on=source.ends_on,
                is_current=source.starts_on <= as_of and (source.ends_on is None or source.ends_on >= as_of),
                stated_net_minor=source.net_minor,
                stated_gross_minor=source.gross_minor,
                observed_mean_minor=mean,
                observed_stdev_minor=stdev,
                receipt_count=count,
                last_received_on=last_on,
                expected_net_minor=expected,
                expected_is_observed=use_observed,
                monthly_net_minor=monthly_equivalent_minor(expected, source.frequency),
                deductions_minor=deductions_for(source),
                anchor=occurrence_anchor(source),
            )
        )
    return views


def _dominant_income_currency() -> str | None:
    """The currency most of the money arrives in.

    Chosen by total monthly value rather than by row count: one salary
    outweighs three small side incomes, and it is the salary's currency the
    household actually lives in.
    """
    totals: dict[str, int] = {}
    counts: dict[str, int] = {}
    today = timezone.localdate()
    for source in IncomeSource.objects.filter(is_active=True):
        if source.starts_on > today or (source.ends_on is not None and source.ends_on < today):
            continue
        counts[source.currency] = counts.get(source.currency, 0) + 1
        monthly = monthly_equivalent_minor(source.net_minor, source.frequency)
        # An ad-hoc source has no monthly value but is still income, and its
        # currency still counts. Skipping it entirely meant a household whose
        # income is *entirely* ad-hoc — gig and freelance workers, the people
        # this model exists for — resolved to no currency, got no summary, and
        # was told they had no income at all. Registering the currency with
        # zero value keeps the total honest and keeps the household visible.
        totals[source.currency] = totals.get(source.currency, 0) + (monthly or 0)
    if not counts:
        return None
    # Value first, then source count as the tie-break, so an all-ad-hoc
    # household still resolves rather than falling to an arbitrary ordering.
    return max(counts, key=lambda c: (totals.get(c, 0), counts[c]))


@dataclass(frozen=True, slots=True)
class IncomeSummary:
    """The household's income position, in one currency."""

    currency: str
    #: Expected net per month across every source with a knowable cadence.
    monthly_net_minor: int
    #: Of which, from sources whose amount is contractually fixed.
    monthly_fixed_minor: int
    monthly_variable_minor: int
    #: Total withheld per month. `None` when any source cannot resolve its
    #: deductions, because a partial total presented as a whole is worse than
    #: no total.
    monthly_deductions_minor: int | None
    source_count: int
    #: Sources whose cadence is ad-hoc and so contribute nothing to the monthly
    #: figure. Reported so the UI can say the total is incomplete rather than
    #: implying these people earn nothing.
    ad_hoc_count: int
    #: Sources that must be rendered speculatively.
    speculative_count: int

    @property
    def monthly_gross_minor(self) -> int | None:
        if self.monthly_deductions_minor is None:
            return None
        return self.monthly_net_minor + self.monthly_deductions_minor

    @property
    def take_home_rate(self) -> float | None:
        """Share of gross that reaches the account, as a percentage.

        The number a payslip never states plainly and the one that decides what
        a raise is actually worth.
        """
        gross = self.monthly_gross_minor
        if gross is None or gross <= 0:
            return None
        return round(self.monthly_net_minor / gross * 100, 1)

    #: Share of monthly income from the single largest source. High
    #: concentration is the household's biggest income risk and it is entirely
    #: invisible in a total: two people with the same income are in very
    #: different positions if one of them earns all of it from one employer.
    #: `None` when there is nothing to concentrate.
    concentration_pct: float | None = None


def income_summary(*, as_of: date | None = None, currency: str | None = None) -> IncomeSummary | None:
    """Aggregate income position, or ``None`` when nothing is recorded."""
    as_of = as_of or timezone.localdate()
    currency = currency or _dominant_income_currency()
    if currency is None:
        return None

    views = [v for v in source_views(as_of=as_of, currency=currency)]
    current = [v for v in views if v.is_current]
    if not current:
        return None

    monthly = [v for v in current if v.monthly_net_minor is not None]
    total = sum(v.monthly_net_minor for v in monthly)

    deduction_parts = []
    for v in monthly:
        if v.deductions_minor is None:
            deduction_parts = None
            break
        per_month = monthly_equivalent_minor(v.deductions_minor, v.frequency)
        deduction_parts.append(per_month or 0)

    largest = max((v.monthly_net_minor for v in monthly), default=0)
    concentration = round(largest / total * 100, 1) if total > 0 else None

    return IncomeSummary(
        currency=currency,
        monthly_net_minor=total,
        monthly_fixed_minor=sum(v.monthly_net_minor for v in monthly if v.reliability == Reliability.FIXED),
        monthly_variable_minor=sum(
            v.monthly_net_minor for v in monthly if v.reliability != Reliability.FIXED
        ),
        monthly_deductions_minor=sum(deduction_parts) if deduction_parts is not None else None,
        source_count=len(current),
        ad_hoc_count=sum(1 for v in current if v.frequency == IncomeFrequency.AD_HOC),
        speculative_count=sum(1 for v in current if v.is_speculative),
        concentration_pct=concentration,
    )


# =============================================================================
# Committed income
# =============================================================================
@dataclass(frozen=True, slots=True)
class CommittedIncome:
    """How much of the month's income is spoken for before any choice is made.

    This is the number personal financial management exists to produce and the
    product could not compute before: it has always known the numerator and
    never had the denominator.
    """

    currency: str
    monthly_income_minor: int
    bills_minor: int
    debt_minimums_minor: int
    recurring_expenses_minor: int

    #: Income that is contractually fixed. The ratio against *this* is the one
    #: that matters for someone on variable pay: commitments are fixed whether
    #: or not the commission arrives.
    monthly_fixed_income_minor: int

    @property
    def committed_minor(self) -> int:
        return self.bills_minor + self.debt_minimums_minor + self.recurring_expenses_minor

    @property
    def free_minor(self) -> int:
        return self.monthly_income_minor - self.committed_minor

    @property
    def committed_pct(self) -> float | None:
        if self.monthly_income_minor <= 0:
            return None
        return round(self.committed_minor / self.monthly_income_minor * 100, 1)

    @property
    def committed_against_fixed_pct(self) -> float | None:
        """The same ratio counting only income that is actually promised.

        Reported separately rather than instead: for a salaried household the
        two are identical and the extra number is noise, but for a freelancer
        the gap between them *is* the finding.
        """
        if self.monthly_fixed_income_minor <= 0:
            return None
        return round(self.committed_minor / self.monthly_fixed_income_minor * 100, 1)


def _monthly_bills_minor(*, currency: str, as_of: date) -> int:
    """Recurring bills, as a monthly figure.

    Only bills that actually recur count. A one-off bill due this month is a
    real obligation but it is not a *commitment* — it does not repeat, so
    including it would make the ratio swing on the timing of a single vet
    visit and make month-to-month comparison meaningless.
    """
    total = 0
    bills = Bill.objects.filter(
        currency=currency,
        status=BillStatus.UPCOMING,
    ).exclude(recurrence_frequency="")
    for bill in bills:
        total += amount_in_month(
            amount_minor=bill.amount_minor,
            frequency=bill.recurrence_frequency,
            interval=bill.recurrence_interval,
            anchor=bill.due_on,
            as_of=as_of,
        )
    return total


def _monthly_recurring_expenses_minor(*, currency: str, as_of: date) -> int:
    """Recurring expense templates, as a monthly figure.

    Transfers are excluded. Moving money to savings is a decision the household
    makes, not a commitment it is bound by, and counting it would report a
    diligent saver as being under more pressure than a spendthrift.

    Templates past `ends_on` are skipped even if still marked active — an
    ended lease is not a commitment, and leaving it in would overstate the
    ratio until someone remembered to pause the schedule.
    """
    total = 0
    templates = RecurringTransaction.objects.filter(
        is_active=True, currency=currency, txn_type=RecurringType.EXPENSE
    )
    for template in templates:
        if template.ends_on is not None and template.ends_on < as_of:
            continue
        total += amount_in_month(
            amount_minor=template.amount_minor,
            frequency=template.frequency,
            interval=template.interval,
            anchor=template.next_run_on,
            as_of=as_of,
            ends_on=template.ends_on,
        )
    return total


def committed_income(*, as_of: date | None = None, currency: str | None = None) -> CommittedIncome | None:
    """What share of income is already committed, or ``None`` without income.

    Returns ``None`` rather than a ratio over zero when no income is recorded.
    A household with commitments and no recorded income is not 100% committed
    or infinitely committed; it is a household that has not told us what it
    earns, and the UI must ask rather than assert.
    """
    as_of = as_of or timezone.localdate()
    summary = income_summary(as_of=as_of, currency=currency)
    if summary is None or summary.monthly_net_minor <= 0:
        return None

    # Debt minimums are filtered to this currency here rather than reusing
    # `debt.selectors.committed_monthly_minor`, which sums every debt's minimum
    # regardless of currency. Against a single-currency income that would
    # silently add a dollar minimum to a shilling salary.
    from apps.debt import selectors as debt_selectors

    debt_minimums = sum(
        v.minimum_payment_minor
        for v in debt_selectors.debt_views(as_of=as_of)
        if v.currency == summary.currency
    )

    return CommittedIncome(
        currency=summary.currency,
        monthly_income_minor=summary.monthly_net_minor,
        monthly_fixed_income_minor=summary.monthly_fixed_minor,
        bills_minor=_monthly_bills_minor(currency=summary.currency, as_of=as_of),
        debt_minimums_minor=debt_minimums,
        recurring_expenses_minor=_monthly_recurring_expenses_minor(currency=summary.currency, as_of=as_of),
    )


def expected_by_recurring(*, currency: str, as_of: date | None = None) -> dict[str, tuple[int, bool]]:
    """Map ``recurring_transaction_id`` -> ``(expected_minor, is_speculative)``.

    Built for the cash-flow calendar, which projects from schedule templates and
    would otherwise draw a variable income at whatever figure the user typed
    into the form months ago. Where receipts exist, the projection should use
    what actually arrived.

    Returned as one map rather than looked up per template so the calendar pays
    two queries regardless of how many income schedules a household has.
    """
    as_of = as_of or timezone.localdate()
    out: dict[str, tuple[int, bool]] = {}
    sources = IncomeSource.objects.filter(
        is_active=True, currency=currency, recurring_transaction__isnull=False
    )
    for source in sources:
        if source.ends_on is not None and source.ends_on < as_of:
            continue
        mean, _stdev, _count, _last = _observed(source, as_of=as_of)
        use_observed = mean is not None and source.reliability != Reliability.FIXED
        expected = mean if use_observed else source.net_minor
        speculative = source.reliability == Reliability.IRREGULAR and not use_observed
        out[str(source.recurring_transaction_id)] = (expected, speculative)
    return out
