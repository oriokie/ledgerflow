"""Payoff simulation — pure arithmetic, no database.

Deliberately free of the ORM so the maths can be tested directly, and so a
what-if ("what if I found another £200 a month?") costs nothing but a function
call. Nothing here reads or writes; the caller assembles the inputs.

The mechanic that makes any payoff plan work is the **rollover**. The monthly
budget stays constant; what changes is how it's split. Every debt gets its
minimum, whatever is left goes to one target debt, and when that debt clears its
minimum joins the pool for the next one. The payments accelerate without the
user finding another penny — which is the entire insight the snowball and
avalanche methods are selling.

Two arithmetic details that are easy to get wrong and materially change the
answer:

**Interest is charged before payment is applied, and payment covers interest
first.** Subtracting the payment from the balance and *then* charging interest
understates the payoff time — by months on a large debt. The order here matches
how lenders actually post.

**A minimum below the monthly interest never pays anything off.** The balance
grows every month regardless. A naive loop runs forever; this detects it and
reports it, because "this debt will never clear at this payment" is real, common
and genuinely actionable information.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

#: Nothing beyond this is a plan. 40 years covers a mortgage from day one.
MAX_MONTHS = 480

class Compounding:
    """How often interest is added to the balance.

    Deliberately plain strings rather than a Django enum: this module has no
    ORM dependency, and the values have to survive being passed in from a
    serializer, a fixture, or a test without importing anything.
    """

    MONTHLY = "monthly"
    DAILY = "daily"
    WEEKLY = "weekly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    CONTINUOUS = "continuous"

    ALL = (MONTHLY, DAILY, WEEKLY, QUARTERLY, ANNUAL, CONTINUOUS)


#: Compounding periods per year. Continuous is handled separately — it is the
#: limit of this sequence, not a member of it.
_PERIODS_PER_YEAR = {
    Compounding.DAILY: Decimal(365),
    Compounding.WEEKLY: Decimal(52),
    Compounding.MONTHLY: Decimal(12),
    Compounding.QUARTERLY: Decimal(4),
    Compounding.ANNUAL: Decimal(1),
}


def equivalent_monthly_rate(apr: Decimal, compounding: str = Compounding.MONTHLY) -> Decimal:
    """Convert an APR at any compounding frequency into one monthly rate.

    This is the move that keeps the simulator simple: every frequency collapses
    to an equivalent monthly figure, so the month-stepping loop never has to
    know how often the lender compounds. Adding a frequency means adding a line
    here, not touching the schedule logic.

    The identity used is (1 + r/n)^(n/12) - 1, which is the monthly-equivalent
    of nominal rate `r` compounded `n` times a year. Continuous compounding is
    the limit of that as n grows: e^(r/12) - 1.

    Ordering follows from the maths and is worth stating, because it is the
    thing a test should pin: annual < monthly < weekly < daily < continuous.
    Compounding more often costs more.
    """
    if apr <= 0:
        return Decimal(0)
    rate = Decimal(apr) / Decimal(100)

    if compounding == Compounding.CONTINUOUS:
        # e^(r/12) - 1, via the Decimal exponential so the result stays exact
        # to the working precision rather than round-tripping through float.
        return (rate / Decimal(12)).exp() - Decimal(1)

    periods = _PERIODS_PER_YEAR.get(compounding)
    if periods is None:
        raise ValueError(f"Unknown compounding frequency {compounding!r}.")

    if compounding == Compounding.MONTHLY:
        # Exact, and avoids a needless fractional power for the common case.
        return rate / Decimal(12)

    # (1 + r/n)^(n/12) - 1, computed as exp(ln(base) * exponent) because
    # Decimal has no fractional pow.
    base = Decimal(1) + rate / periods
    exponent = periods / Decimal(12)
    return (base.ln() * exponent).exp() - Decimal(1)


@dataclass(frozen=True, slots=True)
class RatePeriod:
    """A rate that applies from a date until the next period begins.

    A promotional rate is not a special case: it is simply the first period in
    a schedule whose second period is the standard rate. Modelling both the
    same way means an intro offer, a tracker mortgage and a fixed loan all run
    through one code path.
    """

    effective_from: date
    apr: Decimal


@dataclass(frozen=True, slots=True)
class DebtFees:
    """Charges that are a cost of borrowing but never reduce the principal.

    Fees are capitalised onto the balance rather than paid alongside it, which
    is how a card annual fee actually behaves — it is charged *to* the card and
    then itself accrues interest. Treating fees as a side payment would
    understate what a high-fee product really costs.
    """

    #: Charged every month (maintenance, servicing).
    monthly_minor: int = 0
    #: Charged once a year, in `annual_month`.
    annual_minor: int = 0
    #: Calendar month the annual fee lands in. Defaults to the start month.
    annual_month: int | None = None
    #: One-off, charged at the start of the plan (origination, arrangement).
    origination_minor: int = 0


#: Rounding: money is integer minor units throughout, and interest is rounded
#: half-up per month, matching how a lender posts it.
def _monthly_interest_minor(
    balance_minor: int,
    apr: Decimal,
    *,
    compounding: str = Compounding.MONTHLY,
    offset_minor: int = 0,
) -> int:
    """Interest for one month on a balance, net of any offset.

    `offset_minor` models an offset or linked account: the lender charges
    interest on the balance *less* the offset, without either balance moving.
    Clamped at zero — an offset larger than the debt earns nothing, it just
    stops the interest.
    """
    chargeable = max(0, balance_minor - max(0, offset_minor))
    if chargeable <= 0 or apr <= 0:
        return 0
    monthly_rate = equivalent_monthly_rate(Decimal(apr), compounding)
    return int((Decimal(chargeable) * monthly_rate).quantize(Decimal("1")))


@dataclass(frozen=True, slots=True)
class DebtInput:
    """One debt, as the simulator sees it."""

    debt_id: str
    name: str
    balance_minor: int
    #: The rate used when `rate_schedule` is empty. Retained so every existing
    #: caller keeps working untouched.
    apr: Decimal
    minimum_payment_minor: int
    kind: str = "other"
    custom_priority: int = 100

    #: Rates over time, oldest first. Empty means "use `apr` throughout", which
    #: is what a fixed-rate debt wants and what every pre-existing call site
    #: passes implicitly.
    rate_schedule: tuple[RatePeriod, ...] = ()
    compounding: str = Compounding.MONTHLY
    fees: DebtFees | None = None
    #: Balance of linked offset accounts. Reduces the interest-bearing amount
    #: without either ledger balance changing.
    offset_minor: int = 0

    def apr_on(self, when: date) -> Decimal:
        """The rate in force on a date.

        Walks the schedule for the last period that has started. Before the
        first period begins — a schedule that only describes future changes —
        the base `apr` applies, so a partially-specified timeline degrades to
        the fixed-rate behaviour rather than to zero.
        """
        if not self.rate_schedule:
            return self.apr
        applicable = [p for p in self.rate_schedule if p.effective_from <= when]
        if not applicable:
            return self.apr
        return max(applicable, key=lambda p: p.effective_from).apr


def _fees_for_month(debt: DebtInput, *, month_date: date, month_index: int) -> int:
    """Fees charged in one month.

    The annual fee lands in a single nominated month rather than being spread,
    because that is when it is actually charged and when it actually hurts —
    smoothing it would hide a £150 hit behind a £12.50 average.
    """
    fees = debt.fees
    if fees is None:
        return 0
    total = fees.monthly_minor
    if fees.annual_minor:
        target_month = fees.annual_month or month_date.month
        if month_date.month == target_month:
            total += fees.annual_minor
    # Origination is charged once, at the start of the plan.
    if fees.origination_minor and month_index == 1:
        total += fees.origination_minor
    return total


@dataclass(slots=True)
class DebtProgress:
    """Per-debt outcome of a simulation."""

    debt_id: str
    name: str
    starting_balance_minor: int
    interest_paid_minor: int = 0
    #: Charged separately from interest so the cost breakdown is honest: a
    #: low-rate card with a high annual fee should not look cheap.
    fees_paid_minor: int = 0
    total_paid_minor: int = 0
    months_to_clear: int | None = None
    cleared_on: date | None = None
    #: True when the minimum never covers the interest, so the balance grows
    #: forever. Reported rather than silently looping.
    never_clears: bool = False


@dataclass(frozen=True, slots=True)
class MonthPayment:
    debt_id: str
    name: str
    payment_minor: int
    interest_minor: int
    fee_minor: int
    principal_minor: int
    balance_after_minor: int
    cleared: bool = False


@dataclass(frozen=True, slots=True)
class PayoffMonth:
    month_index: int
    as_of: date
    payments: tuple[MonthPayment, ...]
    total_paid_minor: int
    total_interest_minor: int
    total_fees_minor: int
    remaining_balance_minor: int


@dataclass(slots=True)
class PayoffPlan:
    strategy: str
    currency: str
    monthly_budget_minor: int
    extra_monthly_minor: int
    months: list[PayoffMonth] = field(default_factory=list)
    per_debt: list[DebtProgress] = field(default_factory=list)
    total_interest_minor: int = 0
    total_fees_minor: int = 0
    total_paid_minor: int = 0
    debt_free_on: date | None = None
    months_to_debt_free: int | None = None
    #: Debts whose minimum doesn't cover their interest. While any of these
    #: exist the plan can't complete, and saying so is the useful answer.
    stuck_debt_ids: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return self.debt_free_on is not None


def add_months(anchor: date, months: int) -> date:
    """Calendar-safe month addition, clamping to the end of short months."""
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    if month == 12:
        last_day = 31
    else:
        from datetime import timedelta

        last_day = (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(anchor.day, last_day))


def order_debts(debts: list[DebtInput], strategy: str) -> list[DebtInput]:
    """Payoff order for a strategy.

    Ties are broken deterministically (by balance, then name) so the same
    inputs always produce the same plan — a schedule that reshuffles between
    page loads is not a schedule anyone can follow.
    """
    if strategy == "snowball":
        return sorted(debts, key=lambda d: (d.balance_minor, d.name))
    if strategy == "avalanche":
        return sorted(debts, key=lambda d: (-d.apr, d.balance_minor, d.name))
    if strategy == "custom":
        return sorted(debts, key=lambda d: (d.custom_priority, d.balance_minor, d.name))
    raise ValueError(f"Unknown payoff strategy {strategy!r}.")


def minimum_monthly_minor(debts: list[DebtInput]) -> int:
    """What must be paid each month just to stay current."""
    return sum(d.minimum_payment_minor for d in debts if d.balance_minor > 0)


def simulate(
    debts: list[DebtInput],
    *,
    strategy: str = "avalanche",
    extra_monthly_minor: int = 0,
    extra: "ExtraPayments | None" = None,
    start: date | None = None,
    currency: str = "USD",
    max_months: int = MAX_MONTHS,
) -> PayoffPlan:
    """Run the plan month by month until every debt clears or time runs out.

    `extra_monthly_minor` is money *above* the minimums, applied every month.
    Pass `extra` instead for a lumpy schedule — a bonus in March, a raise from
    month nine — which is how repayment money actually arrives.

    The *minimum* portion of the budget stays constant for the whole plan even
    as debts clear, and that constancy is what produces the rollover
    acceleration. Only the extra portion varies.
    """
    from django.utils import timezone

    start = start or timezone.localdate()
    active = [d for d in debts if d.balance_minor > 0]

    # A constant `extra_monthly_minor` is just the simplest schedule, so it is
    # normalised into one rather than handled twice.
    schedule = extra or ExtraPayments(monthly_minor=max(0, extra_monthly_minor))
    base_minimums = minimum_monthly_minor(active)

    plan = PayoffPlan(
        strategy=strategy,
        currency=currency,
        monthly_budget_minor=base_minimums + schedule.for_month(1),
        extra_monthly_minor=schedule.monthly_minor,
    )
    if not active:
        plan.debt_free_on = start
        plan.months_to_debt_free = 0
        return plan

    ordered = order_debts(active, strategy)
    del active
    balances = {d.debt_id: d.balance_minor for d in ordered}
    progress = {
        d.debt_id: DebtProgress(
            debt_id=d.debt_id, name=d.name, starting_balance_minor=d.balance_minor
        )
        for d in ordered
    }
    by_id = {d.debt_id: d for d in ordered}

    for month_index in range(1, max_months + 1):
        outstanding = [d for d in ordered if balances[d.debt_id] > 0]
        if not outstanding:
            plan.months_to_debt_free = month_index - 1
            plan.debt_free_on = add_months(start, month_index - 1)
            break

        # Everything not being targeted gets exactly its minimum; the target
        # gets whatever the budget leaves. As debts clear, their minimums stop
        # being reserved and flow to the target automatically.
        target = outstanding[0]
        # The minimum pool never shrinks as debts clear — that is the rollover.
        # Only the extra varies, month by month.
        budget = base_minimums + schedule.for_month(month_index)
        reserved = sum(
            d.minimum_payment_minor for d in outstanding if d.debt_id != target.debt_id
        )
        target_payment = max(0, budget - reserved)

        balance_before_month = sum(balances.values())
        month_payments: list[MonthPayment] = []
        month_interest = 0
        month_fees = 0
        month_paid = 0

        month_date = add_months(start, month_index)
        for debt in outstanding:
            balance = balances[debt.debt_id]
            # The rate in force *this month*, so a promo expiry or a tracker
            # change takes effect on the right month rather than being applied
            # retroactively across the whole plan.
            apr = debt.apr_on(month_date)
            interest = _monthly_interest_minor(
                balance,
                apr,
                compounding=debt.compounding,
                offset_minor=debt.offset_minor,
            )
            fee = _fees_for_month(debt, month_date=month_date, month_index=month_index)
            owed = balance + interest + fee

            intended = target_payment if debt.debt_id == target.debt_id else debt.minimum_payment_minor
            # Never pay more than is owed: the final month settles the balance
            # exactly rather than overshooting into a credit.
            payment = min(intended, owed)

            # What actually came off the balance, after interest and fees.
            principal = payment - interest - fee
            new_balance = max(0, owed - payment)
            balances[debt.debt_id] = new_balance

            record = progress[debt.debt_id]
            record.interest_paid_minor += interest
            record.fees_paid_minor += fee
            record.total_paid_minor += payment
            cleared = new_balance == 0
            if cleared and record.months_to_clear is None:
                record.months_to_clear = month_index
                record.cleared_on = add_months(start, month_index)

            month_payments.append(
                MonthPayment(
                    debt_id=debt.debt_id,
                    name=debt.name,
                    payment_minor=payment,
                    interest_minor=interest,
                    fee_minor=fee,
                    principal_minor=principal,
                    balance_after_minor=new_balance,
                    cleared=cleared,
                )
            )
            month_interest += interest
            month_fees += fee
            month_paid += payment

        plan.months.append(
            PayoffMonth(
                month_index=month_index,
                as_of=add_months(start, month_index),
                payments=tuple(month_payments),
                total_paid_minor=month_paid,
                total_interest_minor=month_interest,
                total_fees_minor=month_fees,
                remaining_balance_minor=sum(balances.values()),
            )
        )
        plan.total_interest_minor += month_interest
        plan.total_fees_minor += month_fees
        plan.total_paid_minor += month_paid

        # If the total owed didn't fall this month, it never will: the budget is
        # constant, the ordering deterministic, and next month starts from a
        # balance that is the same or higher. Running on to `max_months` would
        # dress an impossibility up as a 40-year plan.
        #
        # This is the situation of someone whose minimum payment doesn't cover
        # their interest — common, serious, and worth stating plainly rather
        # than burying in a schedule that never ends.
        remaining_now = sum(balances.values())
        future_help = any(at > month_index for at, _ in schedule.lump_sums) or any(
            at > month_index for at, _ in schedule.step_ups
        )
        if remaining_now >= balance_before_month and not future_help:
            plan.stuck_debt_ids = [d.debt_id for d in outstanding if balances[d.debt_id] > 0]
            break

    for debt_id, record in progress.items():
        if record.months_to_clear is None:
            record.never_clears = True
            if debt_id not in plan.stuck_debt_ids and balances[debt_id] > 0:
                plan.stuck_debt_ids.append(debt_id)

    plan.per_debt = [progress[d.debt_id] for d in ordered]
    return plan


@dataclass(frozen=True, slots=True)
class StrategyComparison:
    """One strategy's headline outcome, for comparison against the others."""

    strategy: str
    months_to_debt_free: int | None
    debt_free_on: date | None
    total_interest_minor: int
    #: Against the minimums-only baseline. Zero when there's no extra payment,
    #: because there is then nothing to compare.
    interest_saved_minor: int
    months_saved: int | None
    #: The debt cleared first — the thing snowball is optimising for.
    first_cleared_name: str | None
    first_cleared_months: int | None


def compare_strategies(
    debts: list[DebtInput],
    *,
    extra_monthly_minor: int = 0,
    start: date | None = None,
    currency: str = "USD",
) -> list[StrategyComparison]:
    """Run every strategy against the same inputs.

    Comparison is the honest way to present this. Avalanche always wins on
    total interest and snowball often wins on the first clearance date, and
    which matters more is a judgement about the person, not the arithmetic.

    The baseline for "saved" figures is **minimums only**, which is what
    happens if the user changes nothing. Comparing strategies against each
    other would flatter whichever is listed second.
    """
    baseline = simulate(
        debts, strategy="avalanche", extra_monthly_minor=0, start=start, currency=currency
    )

    out: list[StrategyComparison] = []
    for strategy in ("avalanche", "snowball", "custom"):
        plan = simulate(
            debts,
            strategy=strategy,
            extra_monthly_minor=extra_monthly_minor,
            start=start,
            currency=currency,
        )
        cleared = [p for p in plan.per_debt if p.months_to_clear is not None]
        first = min(cleared, key=lambda p: p.months_to_clear) if cleared else None

        interest_saved = max(0, baseline.total_interest_minor - plan.total_interest_minor)
        months_saved = None
        if baseline.months_to_debt_free is not None and plan.months_to_debt_free is not None:
            months_saved = max(0, baseline.months_to_debt_free - plan.months_to_debt_free)

        out.append(
            StrategyComparison(
                strategy=strategy,
                months_to_debt_free=plan.months_to_debt_free,
                debt_free_on=plan.debt_free_on,
                total_interest_minor=plan.total_interest_minor,
                interest_saved_minor=interest_saved,
                months_saved=months_saved,
                first_cleared_name=first.name if first else None,
                first_cleared_months=first.months_to_clear if first else None,
            )
        )
    return out


def extra_payment_curve(
    debts: list[DebtInput],
    *,
    strategy: str = "avalanche",
    steps: tuple[int, ...] = (0, 5_000, 10_000, 25_000, 50_000, 100_000),
    start: date | None = None,
) -> list[dict]:
    """What each additional monthly amount buys, in months and interest.

    The point of showing a curve rather than a single answer: the returns are
    steeply non-linear at the start, and seeing that the first £50 a month
    saves disproportionately more than the next £50 is the thing that actually
    changes behaviour.
    """
    baseline = simulate(debts, strategy=strategy, extra_monthly_minor=0, start=start)
    out: list[dict] = []
    for extra in steps:
        plan = simulate(debts, strategy=strategy, extra_monthly_minor=extra, start=start)
        out.append(
            {
                "extra_monthly_minor": extra,
                "months_to_debt_free": plan.months_to_debt_free,
                "debt_free_on": plan.debt_free_on,
                "total_interest_minor": plan.total_interest_minor,
                "interest_saved_minor": max(
                    0, baseline.total_interest_minor - plan.total_interest_minor
                ),
                "months_saved": (
                    max(0, baseline.months_to_debt_free - plan.months_to_debt_free)
                    if baseline.months_to_debt_free is not None
                    and plan.months_to_debt_free is not None
                    else None
                ),
            }
        )
    return out


# =============================================================================
# Flexible extra payments
# =============================================================================
@dataclass(frozen=True, slots=True)
class ExtraPayments:
    """Money above the minimums, which rarely arrives at a constant rate.

    Real repayment is lumpy: a bonus in March, a tax refund in July, a raise
    that lifts the monthly figure from month nine. Modelling only a flat
    monthly amount forces users to average those out, which understates how
    quickly a windfall actually clears a debt.

    Tuples rather than dicts so the whole object stays frozen and hashable, and
    can therefore be used in a cache key.
    """

    #: The baseline, applied every month unless overridden.
    monthly_minor: int = 0
    #: (month_index, amount) — replaces the baseline for that month onward.
    #: Models a permanent change, such as a pay rise.
    step_ups: tuple[tuple[int, int], ...] = ()
    #: (month_index, amount) — added on top for that month only.
    lump_sums: tuple[tuple[int, int], ...] = ()

    def for_month(self, month_index: int) -> int:
        """Extra available in a given month (1-based)."""
        base = self.monthly_minor
        applicable = [amount for at, amount in self.step_ups if at <= month_index]
        if applicable:
            # The most recent step-up wins, not the largest — a later reduction
            # is as real as a later increase.
            base = max(
                ((at, amount) for at, amount in self.step_ups if at <= month_index),
                key=lambda pair: pair[0],
            )[1]
        one_off = sum(amount for at, amount in self.lump_sums if at == month_index)
        return max(0, base + one_off)

    @property
    def is_constant(self) -> bool:
        return not self.step_ups and not self.lump_sums


# =============================================================================
# Refinance
# =============================================================================
@dataclass(frozen=True, slots=True)
class RefinanceQuote:
    """Terms being considered. Nothing here touches an existing debt."""

    new_apr: Decimal
    new_minimum_payment_minor: int
    term_months: int | None = None
    #: Arrangement, valuation, legal — anything paid to switch.
    closing_costs_minor: int = 0
    #: Rolled into the new balance rather than paid up front.
    capitalise_costs: bool = True
    compounding: str = Compounding.MONTHLY


@dataclass(frozen=True, slots=True)
class RefinanceResult:
    current_total_cost_minor: int
    new_total_cost_minor: int
    #: Positive means refinancing costs less over the life of the debt.
    lifetime_saving_minor: int
    current_months: int | None
    new_months: int | None
    months_saved: int | None
    current_monthly_minor: int
    new_monthly_minor: int
    #: The month at which cumulative spend under the new deal drops below the
    #: old one. `None` when it never does.
    breakeven_month: int | None
    closing_costs_minor: int
    is_worthwhile: bool


def simulate_refinance(
    debt: DebtInput, quote: RefinanceQuote, *, start: date | None = None
) -> RefinanceResult:
    """Compare a debt against a refinancing offer.

    Simulation only — the existing debt is never modified, and nothing is
    persisted. The caller gets two projections and the difference.

    **Breakeven is the number that decides it.** A lower rate always looks
    better on total interest, but closing costs are paid up front, so a deal
    that saves money over twenty years can cost money over three. The breakeven
    month is when the new deal's cumulative spend finally drops below the old
    one's — and if the user expects to move or repay before then, the "saving"
    never arrives.
    """
    from django.utils import timezone

    start = start or timezone.localdate()

    current = simulate([debt], strategy="avalanche", start=start)

    new_balance = debt.balance_minor + (
        quote.closing_costs_minor if quote.capitalise_costs else 0
    )
    refinanced = DebtInput(
        debt_id=debt.debt_id,
        name=debt.name,
        balance_minor=new_balance,
        apr=quote.new_apr,
        minimum_payment_minor=quote.new_minimum_payment_minor,
        kind=debt.kind,
        compounding=quote.compounding,
    )
    new_plan = simulate([refinanced], strategy="avalanche", start=start)

    upfront = 0 if quote.capitalise_costs else quote.closing_costs_minor
    current_cost = current.total_paid_minor
    new_cost = new_plan.total_paid_minor + upfront

    # Walk both cumulative spends month by month to find the crossover.
    breakeven: int | None = None
    running_current = 0
    running_new = upfront
    for index in range(max(len(current.months), len(new_plan.months))):
        if index < len(current.months):
            running_current += current.months[index].total_paid_minor
        if index < len(new_plan.months):
            running_new += new_plan.months[index].total_paid_minor
        if running_new < running_current:
            breakeven = index + 1
            break

    months_saved = None
    if current.months_to_debt_free is not None and new_plan.months_to_debt_free is not None:
        months_saved = current.months_to_debt_free - new_plan.months_to_debt_free

    saving = current_cost - new_cost
    return RefinanceResult(
        current_total_cost_minor=current_cost,
        new_total_cost_minor=new_cost,
        lifetime_saving_minor=saving,
        current_months=current.months_to_debt_free,
        new_months=new_plan.months_to_debt_free,
        months_saved=months_saved,
        current_monthly_minor=debt.minimum_payment_minor,
        new_monthly_minor=quote.new_minimum_payment_minor,
        breakeven_month=breakeven,
        closing_costs_minor=quote.closing_costs_minor,
        # Worthwhile only if it both saves money and the saving actually
        # arrives — a breakeven that never comes is not a saving.
        is_worthwhile=saving > 0 and breakeven is not None,
    )


# =============================================================================
# Consolidation
# =============================================================================
@dataclass(frozen=True, slots=True)
class ConsolidationQuote:
    new_apr: Decimal
    new_minimum_payment_minor: int
    term_months: int | None = None
    fees_minor: int = 0
    compounding: str = Compounding.MONTHLY


@dataclass(frozen=True, slots=True)
class ConsolidationResult:
    debt_count: int
    combined_balance_minor: int
    current_total_cost_minor: int
    new_total_cost_minor: int
    lifetime_saving_minor: int
    current_months: int | None
    new_months: int | None
    months_saved: int | None
    current_monthly_minor: int
    new_monthly_minor: int
    #: Balance-weighted average of the rates being replaced — the figure the
    #: new rate has to beat.
    current_weighted_apr: float
    new_apr: float
    is_worthwhile: bool


def simulate_consolidation(
    debts: list[DebtInput], quote: ConsolidationQuote, *, start: date | None = None
) -> ConsolidationResult | None:
    """Compare several debts against a single loan replacing them.

    Simulation only; the debts are untouched.

    The comparison that matters is **total cost**, not the monthly payment.
    Consolidation almost always lowers the monthly figure — that is its selling
    point — but stretching the term can raise the lifetime cost even at a lower
    rate. Reporting both, and judging `is_worthwhile` on total cost, keeps the
    cheaper-looking option from being mistaken for the cheaper one.
    """
    from django.utils import timezone

    if len(debts) < 2:
        return None
    start = start or timezone.localdate()

    current = simulate(debts, strategy="avalanche", start=start)
    combined = sum(d.balance_minor for d in debts)

    weighted = 0.0
    if combined > 0:
        weighted = round(
            sum(float(d.apr) * d.balance_minor for d in debts) / combined, 2
        )

    consolidated = DebtInput(
        debt_id="consolidated",
        name="Consolidation loan",
        balance_minor=combined + quote.fees_minor,
        apr=quote.new_apr,
        minimum_payment_minor=quote.new_minimum_payment_minor,
        compounding=quote.compounding,
    )
    new_plan = simulate([consolidated], strategy="avalanche", start=start)

    months_saved = None
    if current.months_to_debt_free is not None and new_plan.months_to_debt_free is not None:
        months_saved = current.months_to_debt_free - new_plan.months_to_debt_free

    saving = current.total_paid_minor - new_plan.total_paid_minor
    return ConsolidationResult(
        debt_count=len(debts),
        combined_balance_minor=combined,
        current_total_cost_minor=current.total_paid_minor,
        new_total_cost_minor=new_plan.total_paid_minor,
        lifetime_saving_minor=saving,
        current_months=current.months_to_debt_free,
        new_months=new_plan.months_to_debt_free,
        months_saved=months_saved,
        current_monthly_minor=minimum_monthly_minor(debts),
        new_monthly_minor=quote.new_minimum_payment_minor,
        current_weighted_apr=weighted,
        new_apr=float(quote.new_apr),
        # Judged on lifetime cost, never on the monthly payment.
        is_worthwhile=saving > 0,
    )
