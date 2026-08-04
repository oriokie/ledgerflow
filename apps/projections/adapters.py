"""Reading the household's real position out of the rest of the product.

This is the *only* module in Phase 1 that queries. The engine, the calculators
and the event compiler are all pure; everything they need to know about the
tenant arrives through here as a `FinancialPosition`. Keeping the boundary this
sharp is what makes a projection reproducible: capture the position once and
the same numbers come out forever, whatever the ledger does afterwards.

Every figure is *measured*, never asked for. The product already knows what the
household earns, spends, owes and holds, and a planner that opens with a
questionnaire is a planner that gets answered aspirationally — people type the
grocery budget they intend to keep, not the one the ledger records. The two
differ by a lot, and only one of them predicts anything.

**Single currency, like everything else in the finance context.** `net_worth()`
and `cashflow_statement()` both refuse to sum across currencies, and so does
this. The dominant liquid currency is projected and named in the result; a
projection that silently added shillings to dollars would be worse than no
projection.
"""

from __future__ import annotations

from datetime import date

from django.utils import timezone

from apps.debt import selectors as debt_selectors
from apps.finance import selectors as finance_selectors
from apps.finance.models import AccountType, FinancialAccount
from apps.investments import selectors as investment_selectors

from .engine import DebtPosition, FinancialPosition

#: Trailing complete months used to measure the household's run rate. Six is
#: the same window `fi.py` uses, deliberately: two modules disagreeing about
#: what "your monthly spending" means is a bug users notice immediately.
HISTORY_MONTHS = 6


class NoPositionError(Exception):
    """Not enough of a financial position to project anything from."""


def _investment_total_minor(currency: str) -> int:
    """Market value of priced holdings in `currency`.

    Unpriced holdings are skipped rather than counted at cost. A cost-basis
    fallback would silently understate a portfolio that has doubled, and the
    investments context already treats "not priced" as distinct from zero.
    """
    total = 0
    for valuation in investment_selectors.holding_valuations():
        if valuation.currency != currency or valuation.market_value_minor is None:
            continue
        total += valuation.market_value_minor
    return total


def _debt_positions(currency: str) -> tuple[DebtPosition, ...]:
    """Real debts, with the payment the household actually makes.

    `minimum_payment_minor` is the right input rather than an amortising
    payment derived from the balance: the question a projection answers is
    "when is this gone given what I pay", and for a lot of people the honest
    answer is "not within this window" — which only the real payment can show.

    **The debt context stores `apr` as a percentage, this one takes fractions.**
    21.5 there is 0.215 here. The two conventions meet exactly at this line and
    nowhere else; `payoff.equivalent_monthly_rate` does the same division on its
    own side of the boundary. Passing the percentage straight through produced a
    500 on every workspace that carried a debt, because the calculator's rate
    guard caught it — which is the guard doing its job, but only after the fact.
    """
    positions = []
    for view in debt_selectors.debt_views():
        if view.currency != currency or view.balance_minor <= 0:
            continue
        positions.append(
            DebtPosition(
                label=view.name,
                balance_minor=view.balance_minor,
                annual_rate=float(view.apr) / 100,
                monthly_payment_minor=view.minimum_payment_minor,
            )
        )
    return tuple(positions)


def _other_assets_minor(currency: str) -> int:
    """Non-liquid, non-investment assets — property, vehicles, valuables.

    Derived by subtraction rather than by a second query: whatever net worth
    counts as an asset that is neither liquid nor an investment holding is, by
    definition, the rest. That keeps this consistent with the net-worth figure
    the user sees elsewhere, which is worth more than a purer taxonomy.
    """
    row = next((r for r in finance_selectors.net_worth() if r.currency == currency), None)
    if row is None:
        return 0
    liquid = finance_selectors.liquid_balance_minor(currency)
    investments = _investment_total_minor(currency)
    return max(0, row.assets_minor - liquid - investments)


def _monthly_flows(currency: str, as_of: date) -> tuple[int, int]:
    """Median monthly net income and expenses over the trailing window.

    Median, not mean, and complete months only — both for the same reason
    `fi.py` does it. One bonus or one holiday drags a mean badly, and the
    current month always looks frugal because it has not finished, so including
    it builds optimism into every projection that follows.
    """
    statement = finance_selectors.cashflow_statement(months=HISTORY_MONTHS + 1, as_of=as_of)
    if statement is None:
        return 0, 0

    current_month = as_of.replace(day=1)
    inflows: list[int] = []
    outflows: list[int] = []
    for row in statement.rows:
        if row.period_start >= current_month:
            continue
        inflows.append(row.inflow_minor)
        outflows.append(row.outflow_minor)

    if not inflows:
        return 0, 0

    def median(values: list[int]) -> int:
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) // 2

    return median(inflows), median(outflows)


def current_position(*, as_of: date | None = None) -> FinancialPosition:
    """Snapshot the household's position for the ambient tenant.

    Raises `NoPositionError` when there is nothing to project from — an empty
    workspace should get an invitation to add an account, not a forty-year
    forecast of zero.
    """
    as_of = as_of or timezone.localdate()

    currency = finance_selectors._dominant_liquid_currency()
    if currency is None:
        raise NoPositionError("No liquid accounts to project from. Add a current or savings account first.")

    liquid = finance_selectors.liquid_balance_minor(currency)
    income, expenses = _monthly_flows(currency, as_of)
    contribution = _monthly_investment_contribution_minor(currency)

    return FinancialPosition(
        currency=currency,
        as_of=as_of,
        liquid_minor=liquid,
        investment_minor=_investment_total_minor(currency),
        other_assets_minor=_other_assets_minor(currency),
        monthly_net_income_minor=income,
        monthly_expenses_minor=expenses,
        monthly_investment_contribution_minor=contribution,
        debts=_debt_positions(currency),
    )


def _monthly_investment_contribution_minor(currency: str) -> int:
    """Recurring transfers into investment accounts.

    Counted separately from expenses because they are not consumption — money
    moved into a brokerage is still the household's. Treating it as spending
    would understate the saving rate and push every projection pessimistic,
    which is the mirror of the optimism this module works to avoid.
    """
    from apps.finance.models import RecurringTransaction, RecurringType

    investment_ids = set(
        FinancialAccount.objects.filter(
            account_type=AccountType.INVESTMENT, archived_at__isnull=True
        ).values_list("id", flat=True)
    )
    if not investment_ids:
        return 0

    total = 0
    recurring_transfers = RecurringTransaction.objects.filter(
        is_active=True, txn_type=RecurringType.TRANSFER, currency=currency
    )
    for recurring in recurring_transfers:
        # `counter_account` is the destination leg of a transfer. A standing
        # order into a brokerage is the signal we want; one *out* of it is a
        # withdrawal and must not be counted as a contribution.
        if recurring.counter_account_id in investment_ids:
            total += _to_monthly_minor(recurring.amount_minor, recurring.frequency, recurring.interval)
    return total


#: Periods per month for each frequency the finance context supports. Only the
#: four in `Frequency` exist; anything else falls back to monthly rather than
#: silently contributing zero.
_FREQUENCY_TO_MONTHLY = {
    "daily": 30.0,
    "weekly": 52 / 12,
    "monthly": 1.0,
    "yearly": 1 / 12,
}


def _to_monthly_minor(amount_minor: int, frequency: str, interval: int = 1) -> int:
    """Monthly equivalent of a recurring amount.

    `interval` is the "every N periods" multiplier the schedule carries — a
    fortnightly standing order is stored as weekly with an interval of two, and
    ignoring it would double the contribution.
    """
    per_month = _FREQUENCY_TO_MONTHLY.get(str(frequency).lower(), 1.0)
    return round(amount_minor * per_month / max(1, interval))
