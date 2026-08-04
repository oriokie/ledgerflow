"""The projection engine — one month at a time, out to forty years.

The engine is deliberately **pure**: it takes a `FinancialPosition`, a set of
`EconomicAssumptions` and a list of `CompiledEvent`s, and returns a projection.
It never queries, never reads the ambient tenant, and never touches the clock
except through the `as_of` it is handed. Everything that knows about the
database lives in `adapters.py`, and everything that knows about the user's
saved scenarios lives in `services.py`.

That separation is not ceremony. A projection is the thing the product will
eventually be judged on — "you said I could afford this" — so it has to be
reproducible from a written-down set of inputs, testable without a database,
and diffable between two runs. A function that reaches for `timezone.now()` in
the middle is none of those things.

**The vocabulary problem, and how it is solved here.** The product promises
fifteen kinds of life event: buying a home, taking a mortgage, a new child,
losing a job, relocating, starting a business. An engine that knows about
fifteen kinds would be fifteen times harder to trust. So the fifteen are a
*compile target*: `events.compile_event` turns each user-facing kind into some
combination of six primitives the engine actually understands —

    a recurring income change, a recurring expense change, a one-off cash
    movement, a change in non-liquid assets, a new debt, and a debt cleared.

Buying a home is not a special case in the engine; it is a one-off cash
movement (the deposit), an asset (the property), a new debt (the mortgage) and
a recurring expense (rates, insurance, upkeep). Everything the engine does to
it, it does to every other event. Adding a sixteenth life event is a change to
the compiler, not to the arithmetic.

**Three honesty rules**, matching the ones already load-bearing in `fi.py`:

1. *Expenses inflate; income does not automatically.* Prices rise whether or
   not you get a raise. Modelling both with the same growth rate quietly
   assumes you keep pace with inflation forever, which flatters every
   projection. Salary growth is its own assumption and defaults lower.
2. *Nothing is smoothed away.* The trough is reported, not just the average,
   because the month you go negative is the month that costs money.
3. *Every assumption is returned with the result.* A projection whose inputs
   the user cannot see is a number they cannot argue with, and one they should
   not trust.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from .calculators import MAX_HORIZON_MONTHS, monthly_rate

__all__ = [
    "DebtPosition",
    "EconomicAssumptions",
    "FinancialPosition",
    "CompiledEvent",
    "ProjectionMonth",
    "ProjectionResult",
    "project",
    "add_months",
]


def add_months(start: date, months: int) -> date:
    """Calendar-correct month arithmetic, clamping to the end of short months.

    The 31st of January plus one month is the 28th of February, not the 3rd of
    March. Getting this wrong shifts every subsequent event by a day and makes
    two runs of the same scenario disagree.
    """
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    # Clamp: day 31 in a 30-day month becomes day 30.
    for day in range(start.day, 27, -1):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return date(year, month, min(start.day, 28))


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EconomicAssumptions:
    """The economic backdrop. Every one of these is user-configurable, because
    the product's standard is that assumptions are arguable rather than baked
    in. The defaults are deliberately unexciting."""

    #: Annual price inflation applied to living expenses.
    annual_inflation: float = 0.05
    #: Annual growth in earned income. Defaults *below* inflation because most
    #: people's pay does not keep pace, and a projection that assumes it does
    #: is telling a comfortable lie.
    annual_salary_growth: float = 0.03
    #: Nominal annual return on invested assets.
    annual_investment_return: float = 0.07
    #: Nominal annual return on cash held in savings.
    annual_cash_return: float = 0.0
    #: Effective (not marginal) tax rate applied to *changes* in gross earned
    #: income. Base income is measured net from the ledger, so it is not taxed
    #: again here — see `FinancialPosition.monthly_net_income_minor`.
    effective_tax_rate: float = 0.0
    #: Annual growth in property values, used for assets introduced by events.
    annual_property_growth: float = 0.04

    def describe(self) -> list[str]:
        return [
            f"Inflation {self.annual_inflation:.2%} a year, applied to living costs.",
            f"Earned income growing {self.annual_salary_growth:.2%} a year.",
            f"Invested assets returning {self.annual_investment_return:.2%} a year, nominal.",
            f"Cash returning {self.annual_cash_return:.2%} a year.",
            f"Changes in gross pay taxed at an effective {self.effective_tax_rate:.2%}.",
            f"Property appreciating {self.annual_property_growth:.2%} a year.",
        ]


@dataclass(frozen=True)
class DebtPosition:
    """A debt the projection has to service. `monthly_payment_minor` is what
    the user actually pays, not what a lender would compute — the two differ
    constantly and the real one is what determines the payoff date."""

    label: str
    balance_minor: int
    annual_rate: float
    monthly_payment_minor: int

    def __post_init__(self) -> None:
        if self.balance_minor < 0:
            raise ValueError(f"debt {self.label!r} has a negative balance")


@dataclass(frozen=True)
class FinancialPosition:
    """Where the household stands on day zero.

    Income is *net* — what actually lands in an account — because that is what
    the ledger can measure and what the household actually spends. Gross-to-net
    conversion is applied only to income *changes* introduced by events, where
    the user is quoting a salary rather than a payslip.
    """

    currency: str
    as_of: date
    liquid_minor: int = 0
    investment_minor: int = 0
    other_assets_minor: int = 0
    monthly_net_income_minor: int = 0
    monthly_expenses_minor: int = 0
    monthly_investment_contribution_minor: int = 0
    debts: tuple[DebtPosition, ...] = ()

    @property
    def net_worth_minor(self) -> int:
        return (
            self.liquid_minor
            + self.investment_minor
            + self.other_assets_minor
            - sum(d.balance_minor for d in self.debts)
        )


@dataclass(frozen=True)
class CompiledEvent:
    """An event reduced to the six primitives the engine understands.

    Produced by `events.compile_event`; the engine never sees a "buy a house",
    only its consequences. `label` survives compilation purely so a projection
    can explain which life event moved a number.
    """

    label: str
    #: Month index (1-based) at which the event takes effect.
    start_month: int
    #: Last month the recurring parts apply, inclusive. None means forever.
    end_month: int | None = None
    #: Recurring, net-of-tax.
    monthly_income_delta_minor: int = 0
    #: Recurring, in today's money — inflated alongside other expenses.
    monthly_expense_delta_minor: int = 0
    #: One-off cash movement at `start_month`. Negative spends.
    one_off_cash_minor: int = 0
    #: One-off change in non-liquid assets at `start_month` (a house, a car).
    asset_delta_minor: int = 0
    #: Annual growth for *this* asset. A house appreciates and a car does not;
    #: applying one rate to both would let a vehicle purchase quietly inflate
    #: net worth for forty years. None falls back to the property assumption.
    asset_annual_growth: float | None = None
    #: A liability taken on at `start_month`.
    new_debt: DebtPosition | None = None
    #: Debts cleared outright at `start_month`, by label.
    clears_debt_labels: tuple[str, ...] = ()
    #: Recurring contribution change to invested assets.
    monthly_investment_delta_minor: int = 0

    def active_in(self, month: int) -> bool:
        if month < self.start_month:
            return False
        return self.end_month is None or month <= self.end_month


# ---------------------------------------------------------------------------
# outputs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ProjectionMonth:
    month: int
    on: date
    income_minor: int
    expenses_minor: int
    debt_payments_minor: int
    net_cashflow_minor: int
    liquid_minor: int
    investment_minor: int
    other_assets_minor: int
    debt_balance_minor: int
    net_worth_minor: int
    #: Life events that took effect this month, for annotating a chart.
    events: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectionResult:
    currency: str
    as_of: date
    months: int
    opening_net_worth_minor: int
    closing_net_worth_minor: int
    #: The trough — the lowest the liquid balance gets, and when.
    lowest_liquid_minor: int
    lowest_liquid_month: int
    #: First month the liquid balance goes negative. None is the good case.
    first_negative_month: int | None
    first_negative_on: date | None
    #: Month the last debt clears. None when debt outlives the window.
    debt_free_month: int | None
    total_interest_paid_minor: int
    points: list[ProjectionMonth] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def closing(self) -> ProjectionMonth | None:
        return self.points[-1] if self.points else None


# ---------------------------------------------------------------------------
# the engine
# ---------------------------------------------------------------------------
def project(
    *,
    position: FinancialPosition,
    assumptions: EconomicAssumptions | None = None,
    events: list[CompiledEvent] | None = None,
    months: int = 120,
) -> ProjectionResult:
    """Roll the position forward month by month.

    The loop order matters and is chosen to be pessimistic where it is
    ambiguous: expenses and debt service are taken out before any return is
    credited, so a month that is tight looks tight rather than being rescued by
    interest that would not have arrived until the end of the period.
    """
    if months <= 0:
        raise ValueError("a projection needs at least one month")
    if months > MAX_HORIZON_MONTHS:
        raise ValueError(f"{months} months exceeds the {MAX_HORIZON_MONTHS}-month ceiling")

    assumptions = assumptions or EconomicAssumptions()
    events = list(events or [])

    inflation_m = monthly_rate(assumptions.annual_inflation, compounding="effective")
    salary_m = monthly_rate(assumptions.annual_salary_growth, compounding="effective")
    invest_m = monthly_rate(assumptions.annual_investment_return, compounding="effective")
    cash_m = monthly_rate(assumptions.annual_cash_return, compounding="effective")
    property_m = monthly_rate(assumptions.annual_property_growth, compounding="effective")

    liquid = float(position.liquid_minor)
    invested = float(position.investment_minor)
    # Non-liquid assets are tracked as tranches rather than one scalar so each
    # carries its own growth rate: the house appreciates while the car it was
    # bought alongside falls off a cliff.
    tranches: list[list[float]] = [[float(position.other_assets_minor), property_m]]
    debts: list[DebtPosition] = list(position.debts)

    total_interest = 0
    lowest_liquid = position.liquid_minor
    lowest_month = 0
    first_negative: int | None = None
    debt_free_month: int | None = None
    points: list[ProjectionMonth] = []
    warnings: list[str] = []

    for month in range(1, months + 1):
        fired: list[str] = []

        # -- one-off effects land at the start of their month ---------------
        for event in events:
            if event.start_month != month:
                continue
            fired.append(event.label)
            liquid += event.one_off_cash_minor
            if event.asset_delta_minor:
                growth = (
                    monthly_rate(event.asset_annual_growth, compounding="effective")
                    if event.asset_annual_growth is not None
                    else property_m
                )
                tranches.append([float(event.asset_delta_minor), growth])
            if event.new_debt is not None:
                debts.append(event.new_debt)
            if event.clears_debt_labels:
                cleared = {label for label in event.clears_debt_labels}
                remaining = []
                for debt in debts:
                    if debt.label in cleared:
                        liquid -= debt.balance_minor
                    else:
                        remaining.append(debt)
                debts = remaining

        # -- recurring flows, grown to this month ---------------------------
        income = position.monthly_net_income_minor * (1 + salary_m) ** month
        expenses = position.monthly_expenses_minor * (1 + inflation_m) ** month
        contribution = float(position.monthly_investment_contribution_minor)

        for event in events:
            if not event.active_in(month):
                continue
            # Income deltas track salary growth from the month they start;
            # expense deltas track inflation. Both are quoted in today's money.
            elapsed = month - event.start_month
            if event.monthly_income_delta_minor:
                income += event.monthly_income_delta_minor * (1 + salary_m) ** elapsed
            if event.monthly_expense_delta_minor:
                expenses += event.monthly_expense_delta_minor * (1 + inflation_m) ** elapsed
            contribution += event.monthly_investment_delta_minor

        # -- debt service ---------------------------------------------------
        debt_payments = 0
        still_owed: list[DebtPosition] = []
        for debt in debts:
            if debt.balance_minor <= 0:
                continue
            i = monthly_rate(debt.annual_rate)
            interest = round(debt.balance_minor * i)
            payment = min(debt.monthly_payment_minor, debt.balance_minor + interest)
            principal = payment - interest
            if principal <= 0 and debt.monthly_payment_minor > 0:
                # The payment does not touch the principal. Say so once rather
                # than silently projecting a debt that never moves.
                message = f"Payments on {debt.label} do not cover its interest; the balance grows."
                if message not in warnings:
                    warnings.append(message)
            new_balance = max(0, debt.balance_minor + interest - payment)
            debt_payments += payment
            total_interest += interest
            if new_balance > 0:
                still_owed.append(replace(debt, balance_minor=new_balance))
        debts = still_owed
        if not debts and debt_free_month is None and position.debts:
            debt_free_month = month

        # -- settle the month ------------------------------------------------
        net_cashflow = round(income) - round(expenses) - debt_payments - round(contribution)
        liquid += net_cashflow
        # Returns credited after the month's obligations, so a tight month
        # reads as tight.
        liquid *= 1 + cash_m
        invested = invested * (1 + invest_m) + contribution
        for tranche in tranches:
            tranche[0] *= 1 + tranche[1]

        liquid_minor = round(liquid)
        other_assets_minor = round(sum(t[0] for t in tranches))
        debt_balance = sum(d.balance_minor for d in debts)
        net_worth = liquid_minor + round(invested) + other_assets_minor - debt_balance

        if liquid_minor < lowest_liquid:
            lowest_liquid = liquid_minor
            lowest_month = month
        if first_negative is None and liquid_minor < 0:
            first_negative = month

        points.append(
            ProjectionMonth(
                month=month,
                on=add_months(position.as_of, month),
                income_minor=round(income),
                expenses_minor=round(expenses),
                debt_payments_minor=debt_payments,
                net_cashflow_minor=net_cashflow,
                liquid_minor=liquid_minor,
                investment_minor=round(invested),
                other_assets_minor=other_assets_minor,
                debt_balance_minor=debt_balance,
                net_worth_minor=net_worth,
                events=tuple(fired),
            )
        )

    notes = list(assumptions.describe())
    notes.append(
        "Recurring amounts are quoted in today's money and grown from there; balances shown are nominal."
    )
    if position.monthly_net_income_minor == 0:
        warnings.append("No recurring income recorded, so the projection only spends down what is held.")

    return ProjectionResult(
        currency=position.currency,
        as_of=position.as_of,
        months=months,
        opening_net_worth_minor=position.net_worth_minor,
        closing_net_worth_minor=points[-1].net_worth_minor if points else position.net_worth_minor,
        lowest_liquid_minor=lowest_liquid,
        lowest_liquid_month=lowest_month,
        first_negative_month=first_negative,
        first_negative_on=add_months(position.as_of, first_negative) if first_negative else None,
        debt_free_month=debt_free_month,
        total_interest_paid_minor=total_interest,
        points=points,
        assumptions=notes,
        warnings=warnings,
    )
