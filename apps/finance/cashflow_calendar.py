"""Cash flow calendar — a day-by-day projection of liquid balance.

Answers the question a monthly summary cannot: *"will I go negative before
payday, and on which day?"* Month totals routinely look healthy while the
balance dips below zero mid-month, and that dip is what actually costs a user
an overdraft fee.

Everything here is **projection, not record**. No ledger entry is written, and
nothing is cached — a stale forecast is worse than a slow one. The calendar
reads three sources of known future movement:

  * ``RecurringTransaction`` — templates that auto-post on a schedule. Covers
    salary, subscriptions, loan payments, and standing transfers.
  * ``Bill`` — money owed and not yet paid, including future occurrences of a
    recurring bill that hasn't been paid forward yet.
  * current liquid balances — the starting point the projection runs from.

**What it does NOT read is the point of `everyday_spending`.** Those three
sources are all *scheduled* money. Nothing in them accounts for groceries,
fuel, or a coffee — which for most people is the largest outflow there is. A
projection built from schedules alone is therefore not merely uncertain, it is
**systematically optimistic**: it draws a flat line across a fortnight in which
the user will certainly spend money, and it will say "you are fine" to someone
who is not. `everyday_spending` measures that outflow from history so the
calendar can show the range it actually lands in.

Two disciplines are inherited from the rest of the finance module and are not
negotiable here:

**Single currency.** Like ``net_worth`` and ``cashflow_statement``, this refuses
to sum across currencies. It projects the dominant liquid currency and reports
which one, so the UI can be honest rather than silently adding euros to dollars.

**Transfers between in-scope accounts net to zero.** Moving money from checking
to savings does not change how much cash you hold. Counting it as an outflow
would manufacture a fake dip and, worse, a fake overdraft warning — the single
most damaging thing this feature could get wrong. Only the leg that crosses the
boundary of the projected set counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.utils import timezone

from .models import (
    Bill,
    BillStatus,
    FinancialAccount,
    RecurringTransaction,
    RecurringType,
    Transaction,
    TransactionSource,
    TransactionStatus,
)
from .schedule import nth_occurrence
from .selectors import _LIQUID_TYPES, _dominant_liquid_currency, liquid_balance_minor

#: Default projection window. Long enough to cover a full pay cycle plus the
#: month after it, short enough that the compounding uncertainty of a forecast
#: stays defensible.
DEFAULT_HORIZON_DAYS = 60

#: Hard ceiling. Beyond a year, a projection built from today's schedule is
#: fiction — schedules change, and the calendar shouldn't imply otherwise.
MAX_HORIZON_DAYS = 365

#: Cap on occurrences expanded from a single template, so a daily schedule over
#: a long window can't produce an unbounded series.
MAX_OCCURRENCES_PER_TEMPLATE = 400


class EventSource:
    """Where a projected movement came from. Drives colour coding in the UI."""

    SALARY = "salary"
    INCOME = "income"
    BILL = "bill"
    SUBSCRIPTION = "subscription"
    RECURRING_EXPENSE = "recurring_expense"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"


@dataclass(frozen=True, slots=True)
class CashflowEvent:
    """One expected movement on one day."""

    occurs_on: date
    #: Signed: positive is money in, negative is money out. Signing here means
    #: the running-balance loop is a plain sum with no branch on type — the
    #: place a sign error would otherwise hide.
    amount_minor: int
    description: str
    source: str
    currency: str
    account_id: str | None = None
    account_name: str = ""
    category_name: str = ""
    #: True for a Bill that is already past its due date.
    is_overdue: bool = False
    #: Origin ids, so the UI can deep-link back to the underlying record.
    bill_id: str | None = None
    recurring_id: str | None = None
    #: True when the amount comes from an income source the user marked
    #: irregular and which has no receipt history to measure instead. The
    #: figure is a hope, and the UI may not draw it like a fact.
    is_speculative: bool = False


@dataclass(frozen=True, slots=True)
class EverydaySpending:
    """Typical unscheduled outflow per day, measured from history.

    "Unscheduled" is `source != RECURRING` and not part of a transfer between
    projected accounts — the same exclusion the calendar itself applies, so the
    band cannot double-count what the schedule already knows.

    Carries the **mean and standard deviation**, not the median and quartiles.
    That distinction is the whole correctness of the band, and the first draft
    got it wrong: for a *cumulative* projection the expected total over k days
    is `k x mean`, never `k x median`. On bursty spending — and everyone's
    spending is bursty — the median day is often zero, which produced a
    "likely" line sitting exactly on top of the scheduled one and quietly
    reinstated the very optimism the band exists to correct.

    For the same reason the spread grows as `sqrt(k)`, not `k`: independent
    daily variation partly cancels over a window, so summing a p75 day 45 times
    describes a scenario far more extreme than a p75 45-day total.
    """

    #: Mean daily unscheduled outflow, in minor units (positive = spent).
    mean_minor: int
    #: Standard deviation of the daily figure. The band's width comes from this.
    stdev_minor: int
    #: Median day, reported because it is the more intuitive "typical day" —
    #: used for description only, never for projecting a total.
    median_minor: int
    #: Days of history the estimate is built from.
    observed_days: int
    #: Days in that window with any unscheduled spending at all.
    active_days: int


#: Below this there is not enough history to characterise a spending habit, and
#: a band drawn from a fortnight of a new account would be invented precision.
MIN_HISTORY_DAYS = 28


def everyday_spending(
    *, currency: str, in_scope: set, as_of: date | None = None, window_days: int = 90
) -> EverydaySpending | None:
    """Measure unscheduled daily outflow over a trailing window.

    `None` when there is too little history. An absent band is a true statement
    about what the product knows; a zero-width one would claim the user spends
    nothing outside their schedule.
    """
    as_of = as_of or timezone.localdate()
    start = as_of - timedelta(days=window_days)
    if window_days < MIN_HISTORY_DAYS:
        return None

    rows = (
        Transaction.objects.filter(
            financial_account_id__in=in_scope,
            currency=currency,
            amount_minor__lt=0,
            occurred_at__date__gte=start,
            occurred_at__date__lt=as_of,
        )
        .exclude(source=TransactionSource.RECURRING)
        .exclude(status=TransactionStatus.VOID)
        .values_list("occurred_at", "amount_minor", "transfer_group", "counter_account_id")
    )

    by_day: dict[date, int] = {}
    for occurred_at, amount_minor, transfer_group, counter_account_id in rows:
        # A transfer between two projected accounts nets to zero — counting its
        # outgoing leg would manufacture spending that never left.
        #
        # `str()` is load-bearing: `_liquid_account_ids` returns strings and the
        # queryset yields `UUID`, so the membership test silently never matched
        # and every internal transfer was being counted as everyday spending.
        if transfer_group is not None and str(counter_account_id) in in_scope:
            continue
        by_day[occurred_at.date()] = by_day.get(occurred_at.date(), 0) + (-amount_minor)

    if not by_day:
        return None

    observed = (as_of - start).days
    if observed < MIN_HISTORY_DAYS:
        return None

    # Every day in the window counts, including the ones with no spending —
    # they are exactly what makes the typical day cheaper than the active one.
    series = sorted(by_day.get(start + timedelta(days=i), 0) for i in range(observed))

    n = len(series)
    mean = sum(series) / n
    variance = sum((x - mean) ** 2 for x in series) / n
    median = series[n // 2] if n % 2 else (series[n // 2 - 1] + series[n // 2]) // 2

    return EverydaySpending(
        mean_minor=round(mean),
        stdev_minor=round(variance**0.5),
        median_minor=int(median),
        observed_days=observed,
        active_days=len(by_day),
    )


@dataclass(slots=True)
class CalendarDay:
    day: date
    opening_minor: int
    closing_minor: int
    events: list[CashflowEvent] = field(default_factory=list)
    #: Where the balance is likely to land once ordinary unscheduled spending is
    #: included. `None` when there is too little history to say. These bracket
    #: `closing_minor` from below — everyday spending only ever takes money out,
    #: so the scheduled line is the optimistic edge of the range, never the
    #: middle of it.
    expected_minor: int | None = None
    expected_low_minor: int | None = None
    expected_high_minor: int | None = None

    @property
    def inflow_minor(self) -> int:
        return sum(e.amount_minor for e in self.events if e.amount_minor > 0)

    @property
    def outflow_minor(self) -> int:
        return -sum(e.amount_minor for e in self.events if e.amount_minor < 0)

    @property
    def net_minor(self) -> int:
        return sum(e.amount_minor for e in self.events)

    @property
    def is_negative(self) -> bool:
        """Projected to close below zero — a predicted overdraft."""
        return self.closing_minor < 0

    @property
    def has_events(self) -> bool:
        return bool(self.events)


@dataclass(frozen=True, slots=True)
class CashflowCalendar:
    currency: str
    start: date
    end: date
    opening_balance_minor: int
    days: list[CalendarDay]
    #: How the band above was measured. `None` when it could not be.
    everyday: EverydaySpending | None = None

    @property
    def closing_balance_minor(self) -> int:
        return self.days[-1].closing_minor if self.days else self.opening_balance_minor

    @property
    def lowest_balance_minor(self) -> int:
        """The trough. This — not the closing balance — is what tells a user
        whether they'll survive the month."""
        return min((d.closing_minor for d in self.days), default=self.opening_balance_minor)

    @property
    def lowest_balance_on(self) -> date | None:
        if not self.days:
            return None
        return min(self.days, key=lambda d: d.closing_minor).day

    @property
    def first_negative_on(self) -> date | None:
        """The first projected overdraft, or None. The single most actionable
        figure the calendar produces."""
        for d in self.days:
            if d.is_negative:
                return d.day
        return None

    @property
    def negative_day_count(self) -> int:
        return sum(1 for d in self.days if d.is_negative)

    # ------------------------------------------------------------ safe to spend
    #
    # "How much could I spend today without breaking anything?" is the question
    # every other figure here only gestures at. The answer is the projected
    # trough, floored at zero: money spent today lowers every later day's
    # balance by the same amount, so the binding constraint is the lowest point
    # of the projection, not today's balance — today's balance is exactly the
    # number that lies, because rent hasn't happened yet.
    #
    # Where the everyday-spending band is available, the trough is taken from
    # its *low* edge, so the answer means "beyond your normal habits" rather
    # than "if you stop buying groceries" — a safe-to-spend that assumes the
    # user stops living is a number that gets someone overdrawn. Without
    # history to measure the band, the scheduled line is all there is, and
    # `safe_to_spend_basis` says so, so the UI can caveat honestly.

    @property
    def safe_to_spend_minor(self) -> int:
        floor = min(
            (
                d.expected_low_minor if d.expected_low_minor is not None else d.closing_minor
                for d in self.days
            ),
            default=self.opening_balance_minor,
        )
        return max(0, floor)

    @property
    def safe_to_spend_basis(self) -> str:
        """ "everyday" when normal unscheduled spending is already accounted
        for; "scheduled" when only bills and templates could be projected."""
        return "everyday" if self.everyday is not None else "scheduled"


def _liquid_account_ids(currency: str) -> set[str]:
    """Accounts the projection runs over: active, liquid, in the target
    currency, not archived, and not excluded from reporting."""
    return {
        str(pk)
        for pk in FinancialAccount.objects.filter(
            is_active=True,
            archived_at__isnull=True,
            account_type__in=_LIQUID_TYPES,
            currency=currency,
        ).values_list("id", flat=True)
    }


def _classify_expense(recurring: RecurringTransaction) -> str:
    """Subscriptions are the expense class users most want to see picked out,
    and the loan/utility distinction is already carried by the category."""
    category = getattr(recurring.category, "name", "") or ""
    if "subscription" in category.lower():
        return EventSource.SUBSCRIPTION
    return EventSource.RECURRING_EXPENSE


#: Income kinds that arrive on a payday the user navigates by. Rental income
#: and dividends are income; neither is the thing "can I make it to payday?"
#: is asking about.
PAYDAY_KINDS = frozenset({"employment", "pension", "benefits"})


def _classify_income(recurring: RecurringTransaction) -> str:
    """Salary gets its own marker because it's the anchor users navigate the
    calendar by — "can I make it to payday?" is the question being asked.

    This used to search the template's memo for the English words "salary",
    "payroll", "wage" and "paycheck". That was the one place in this product
    where a figure was derived from a name, and it failed hardest for the users
    the demo data describes: a household paid in KES whose memo reads
    "Mshahara" got no payday marker at all.

    It now reads ``income.IncomeSource.kind`` — a field the user set, in a
    model built for the purpose. Templates with no source attached fall through
    to generic income rather than being guessed at; existing schedules were
    given sources by ``income.0003_backfill_from_recurring_income``, so the
    fallback is for templates created outside the income screen, not for the
    installed base.
    """
    # Reverse one-to-one: Django's RelatedObjectDoesNotExist subclasses
    # AttributeError precisely so this getattr is the supported idiom.
    source = getattr(recurring, "income_source", None)
    if source is not None and source.kind in PAYDAY_KINDS:
        return EventSource.SALARY
    return EventSource.INCOME


def _recurring_events(*, currency: str, start: date, end: date, in_scope: set[str]) -> list[CashflowEvent]:
    """Expand active recurring templates into dated occurrences in the window.

    Occurrences come from ``nth_occurrence`` against the original anchor rather
    than repeated increments, so a "31st of the month" schedule doesn't drift to
    the 28th after one short month.
    """
    events: list[CashflowEvent] = []

    # Imported here rather than at module scope: the income app reads finance
    # models, and a top-level import in both directions is a cycle waiting for
    # someone to add one more line.
    from apps.income.selectors import expected_by_recurring

    expected_income = expected_by_recurring(currency=currency)

    templates = RecurringTransaction.objects.filter(
        is_active=True, currency=currency, next_run_on__lte=end
    ).select_related("financial_account", "counter_account", "category", "payee", "income_source")

    for template in templates:
        account_id = str(template.financial_account_id)
        counter_id = str(template.counter_account_id) if template.counter_account_id else None
        source_in = account_id in in_scope
        counter_in = counter_id in in_scope if counter_id else False

        # Nothing in scope means nothing to project onto this balance.
        if not source_in and not counter_in:
            continue

        # A transfer wholly inside the projected set moves money between two
        # counted accounts: the total is unchanged. Counting it would invent a
        # dip that never happens.
        if template.txn_type == RecurringType.TRANSFER and source_in and counter_in:
            continue

        for n in range(MAX_OCCURRENCES_PER_TEMPLATE):
            occurs = nth_occurrence(
                starts_on=template.next_run_on,
                frequency=template.frequency,
                interval=template.interval,
                n=n,
            )
            if occurs > end:
                break
            if template.ends_on and occurs > template.ends_on:
                break
            if (
                template.max_occurrences is not None
                and template.occurrences_created + n >= template.max_occurrences
            ):
                break
            if occurs < start:
                continue

            label = template.memo or getattr(template.payee, "name", "") or "Recurring"

            if template.txn_type == RecurringType.INCOME:
                # A schedule template stores one fixed number. Real variable
                # income is not one number, and the figure typed into the form
                # months ago is the least informed estimate available once
                # receipts exist. `expected` prefers the measured mean.
                expected, speculative = expected_income.get(str(template.id), (template.amount_minor, False))
                events.append(
                    CashflowEvent(
                        occurs_on=occurs,
                        amount_minor=expected,
                        is_speculative=speculative,
                        description=label,
                        source=_classify_income(template),
                        currency=currency,
                        account_id=account_id,
                        account_name=template.financial_account.name,
                        category_name=getattr(template.category, "name", "") or "",
                        recurring_id=str(template.id),
                    )
                )
            elif template.txn_type == RecurringType.EXPENSE:
                events.append(
                    CashflowEvent(
                        occurs_on=occurs,
                        amount_minor=-template.amount_minor,
                        description=label,
                        source=_classify_expense(template),
                        currency=currency,
                        account_id=account_id,
                        account_name=template.financial_account.name,
                        category_name=getattr(template.category, "name", "") or "",
                        recurring_id=str(template.id),
                    )
                )
            else:
                # A transfer with exactly one leg in scope really does change
                # the projected balance — e.g. a standing payment to an external
                # credit card, or an incoming transfer from an account we don't
                # project.
                leaving = source_in
                events.append(
                    CashflowEvent(
                        occurs_on=occurs,
                        amount_minor=-template.amount_minor if leaving else template.amount_minor,
                        description=label,
                        source=EventSource.TRANSFER_OUT if leaving else EventSource.TRANSFER_IN,
                        currency=currency,
                        account_id=account_id if leaving else counter_id,
                        account_name=(
                            template.financial_account.name
                            if leaving
                            else getattr(template.counter_account, "name", "")
                        ),
                        recurring_id=str(template.id),
                    )
                )
    return events


def _bill_events(*, currency: str, start: date, end: date, today: date) -> list[CashflowEvent]:
    """Unpaid bills in the window, plus projected future occurrences of
    recurring ones.

    A recurring bill only spawns its successor when it's paid, so the stored row
    covers just the next instance. Projecting the rest from
    ``recurrence_frequency`` is what stops a calendar from showing rent once and
    then implying three rent-free months.

    Overdue bills are pulled forward to `start`: the money hasn't left yet, so
    it still belongs in the projection, and dropping it would overstate the
    balance.
    """
    events: list[CashflowEvent] = []
    bills = Bill.objects.filter(
        currency=currency,
        status__in=[BillStatus.UPCOMING, BillStatus.OVERDUE],
        due_on__lte=end,
    ).select_related("payee", "category", "autopay_account")

    for bill in bills:
        overdue = bill.due_on < today
        first_on = max(bill.due_on, start)
        events.append(
            CashflowEvent(
                occurs_on=first_on,
                amount_minor=-bill.amount_minor,
                description=bill.name,
                source=EventSource.BILL,
                currency=currency,
                account_id=str(bill.autopay_account_id) if bill.autopay_account_id else None,
                account_name=getattr(bill.autopay_account, "name", "") or "",
                category_name=getattr(bill.category, "name", "") or "",
                is_overdue=overdue,
                bill_id=str(bill.id),
            )
        )

        if not bill.recurrence_frequency:
            continue
        for n in range(1, MAX_OCCURRENCES_PER_TEMPLATE):
            occurs = nth_occurrence(
                starts_on=bill.due_on,
                frequency=bill.recurrence_frequency,
                interval=bill.recurrence_interval or 1,
                n=n,
            )
            if occurs > end:
                break
            if occurs < start:
                continue
            events.append(
                CashflowEvent(
                    occurs_on=occurs,
                    amount_minor=-bill.amount_minor,
                    description=bill.name,
                    source=EventSource.BILL,
                    currency=currency,
                    account_id=str(bill.autopay_account_id) if bill.autopay_account_id else None,
                    account_name=getattr(bill.autopay_account, "name", "") or "",
                    category_name=getattr(bill.category, "name", "") or "",
                    bill_id=str(bill.id),
                )
            )
    return events


def cashflow_calendar(
    *,
    start: date | None = None,
    days: int = DEFAULT_HORIZON_DAYS,
    currency: str | None = None,
) -> CashflowCalendar | None:
    """Day-by-day projected liquid balance over a window.

    Returns `None` when the workspace holds no liquid account to project — an
    empty calendar would imply a zero balance, which is a claim rather than an
    absence.

    The projection starts from today's *actual* liquid balance, so day one is
    fact and every day after it is inference. That distinction is the whole
    reason the calendar can be trusted.
    """
    today = timezone.localdate()
    start = start or today
    horizon = max(1, min(days, MAX_HORIZON_DAYS))
    end = start + timedelta(days=horizon - 1)

    currency = currency or _dominant_liquid_currency()
    if currency is None:
        return None

    in_scope = _liquid_account_ids(currency)
    opening = liquid_balance_minor(currency)

    events = [
        *_recurring_events(currency=currency, start=start, end=end, in_scope=in_scope),
        *_bill_events(currency=currency, start=start, end=end, today=today),
    ]

    by_day: dict[date, list[CashflowEvent]] = {}
    for event in events:
        by_day.setdefault(event.occurs_on, []).append(event)

    everyday = everyday_spending(currency=currency, in_scope={str(a) for a in in_scope}, as_of=today)

    calendar_days: list[CalendarDay] = []
    running = opening
    # Everyday spending accumulates: the band widens with distance, which is
    # the honest shape. Uncertainty about tomorrow is small; uncertainty about
    # the day after next month is not.
    projected_days = 0
    for offset in range(horizon):
        day = start + timedelta(days=offset)
        day_events = sorted(by_day.get(day, []), key=lambda e: (e.amount_minor, e.description))
        opening_for_day = running
        running += sum(e.amount_minor for e in day_events)

        if everyday is not None and day > today:
            projected_days += 1

        expected = low = high = None
        if everyday is not None:
            # Expected total spend grows linearly; its uncertainty grows with
            # the square root of the horizon, because independent daily
            # variation partly cancels over a window.
            drift = everyday.mean_minor * projected_days
            spread = round(everyday.stdev_minor * (projected_days**0.5))
            expected = running - drift
            low = expected - spread
            high = min(running, expected + spread)

        calendar_days.append(
            CalendarDay(
                day=day,
                opening_minor=opening_for_day,
                closing_minor=running,
                events=day_events,
                expected_minor=expected,
                expected_low_minor=low,
                expected_high_minor=high,
            )
        )

    return CashflowCalendar(
        currency=currency,
        start=start,
        end=end,
        opening_balance_minor=opening,
        days=calendar_days,
        everyday=everyday,
    )


def cashflow_day(*, day: date, currency: str | None = None) -> CalendarDay | None:
    """A single day's detail, with the running balance it inherits.

    Projected from today rather than from the day itself, because the opening
    balance on a future day only means something if every movement between now
    and then has been applied.
    """
    today = timezone.localdate()
    if day < today:
        # The past is record, not projection — callers should read the ledger.
        return None
    horizon = (day - today).days + 1
    calendar = cashflow_calendar(days=min(horizon, MAX_HORIZON_DAYS), currency=currency)
    if calendar is None:
        return None
    for candidate in calendar.days:
        if candidate.day == day:
            return candidate
    return None
