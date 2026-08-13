"""Reading the household's real position out of the rest of the product.

This is the *only* module in Phase 1 that queries. The engine, the calculators
and the event compiler are all pure; everything they need to know about the
tenant arrives through here as a `FinancialPosition`. Keeping the boundary this
sharp is what makes a projection reproducible: capture the position once and
the same numbers come out forever, whatever the ledger does afterwards.

Every figure is *measured*, never asked for — with one honest exception.
The product already knows what the household earns, spends, owes and holds, and
a planner that opens with a questionnaire is a planner that gets answered
aspirationally. Recurring income and expenses captured under Recurring (and
income sources) are not a questionnaire: they are the household's own plan,
including when that plan ends. History still leads; a known schedule floors
the run-rate when history has not caught up yet, and an `ends_on` drops it
from the months after it stops.

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
from apps.finance.models import AccountType, FinancialAccount, RecurringTransaction, RecurringType
from apps.investments import selectors as investment_selectors

from .engine import CompiledEvent, DebtPosition, FinancialPosition, project

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


def _month_offset(as_of: date, when: date) -> int:
    """Calendar months from `as_of`'s month to `when`'s. 0 is the same month."""
    return (when.year - as_of.year) * 12 + (when.month - as_of.month)


def _scheduled_run_rate(currency: str, as_of: date) -> tuple[int, int, list[CompiledEvent]]:
    """Known forward income and expenses, plus events that start or end them.

    History is what happened; a schedule is what is promised. A salary entered
    last week has not yet reached the median of trailing months, and a lease
    that ends in six months must not be projected as a forty-year rent. Both
    numbers live here so the engine can apply the known plan and drop it when
    it actually stops.

    Linked income sources and their posting templates are the same money —
    counting both would double every paycheck.
    """
    from apps.common.tenant_context import get_current_tenant_id
    from apps.income.models import IncomeSource
    from apps.income.selectors import source_views

    if get_current_tenant_id() is None:
        return 0, 0, []

    events: list[CompiledEvent] = []
    income = 0
    expenses = 0

    linked_template_ids = set(
        IncomeSource.objects.filter(recurring_transaction_id__isnull=False).values_list(
            "recurring_transaction_id", flat=True
        )
    )

    def apply(label: str, monthly: int, kind: str, starts_on: date, ends_on: date | None) -> None:
        nonlocal income, expenses
        if monthly <= 0:
            return
        if ends_on is not None and ends_on < as_of:
            return

        income_delta = monthly if kind == "income" else 0
        expense_delta = monthly if kind == "expense" else 0
        start_offset = _month_offset(as_of, starts_on)
        last_offset = _month_offset(as_of, ends_on) if ends_on is not None else None

        if start_offset > 0:
            # Has not started yet — the base run-rate must not include it.
            events.append(
                CompiledEvent(
                    label=label,
                    start_month=start_offset,
                    end_month=last_offset if last_offset and last_offset >= start_offset else None,
                    monthly_income_delta_minor=income_delta,
                    monthly_expense_delta_minor=expense_delta,
                )
            )
            return

        # Already running. Engine month 1 is next calendar month, so a schedule
        # that ends this month does not belong in the forward run-rate at all.
        if last_offset is not None and last_offset < 1:
            return

        if kind == "income":
            income += monthly
        else:
            expenses += monthly
        if last_offset is not None:
            events.append(
                CompiledEvent(
                    label=f"{label} ends",
                    start_month=last_offset + 1,
                    monthly_income_delta_minor=-income_delta,
                    monthly_expense_delta_minor=-expense_delta,
                )
            )

    for view in source_views(as_of=as_of, currency=currency):
        monthly = view.monthly_net_minor or 0
        apply(view.name, monthly, "income", view.starts_on, view.ends_on)

    templates = RecurringTransaction.objects.filter(
        is_active=True, currency=currency, txn_type__in=[RecurringType.INCOME, RecurringType.EXPENSE]
    )
    for template in templates:
        if template.id in linked_template_ids:
            continue
        kind = "income" if template.txn_type == RecurringType.INCOME else "expense"
        monthly = _to_monthly_minor(template.amount_minor, template.frequency, template.interval)
        label = template.memo.strip() or ("Recurring income" if kind == "income" else "Recurring expense")
        apply(label, monthly, kind, template.starts_on, template.ends_on)

    return income, expenses, events


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
    history_income, history_expenses = _monthly_flows(currency, as_of)
    scheduled_income, scheduled_expenses, _events = _scheduled_run_rate(currency, as_of)
    debts = _debt_positions(currency)
    # Known schedules floor the run-rate: a salary set up last week has not
    # reached the trailing median yet, and must still be projected. History
    # above the schedule is unscheduled flow (freelance, everyday spend) and
    # is kept. Debt service is applied by the engine from `debts`, so any
    # of it already sitting in the expense median would be counted twice.
    debt_service = sum(d.monthly_payment_minor for d in debts)
    income = max(history_income, scheduled_income)
    expenses = max(0, max(history_expenses, scheduled_expenses) - debt_service)
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
        debts=debts,
    )


def schedule_adjustments(position: FinancialPosition) -> list[CompiledEvent]:
    """Start/end events for schedules the run-rate itself cannot expire.

    The position carries this month's promised income and expenses as a
    constant. Anything with an `ends_on` (or a start still in the future)
    becomes a compiled event so the engine drops or introduces it on the
    right month rather than projecting a finished contract for forty years.
    """
    _income, _expenses, events = _scheduled_run_rate(position.currency, position.as_of)
    return events


def project_live(
    *,
    position: FinancialPosition,
    assumptions=None,
    events: list[CompiledEvent] | None = None,
    months: int = 120,
):
    """Project a live household, honouring known schedule start and end dates.

    Pure `engine.project` stays ignorant of the database; this is the seam
    that feeds it the dates the rest of the product already stores.
    """
    return project(
        position=position,
        assumptions=assumptions,
        events=[*schedule_adjustments(position), *(events or [])],
        months=months,
    )


def _monthly_investment_contribution_minor(currency: str) -> int:
    """Recurring transfers into investment accounts.

    Counted separately from expenses because they are not consumption — money
    moved into a brokerage is still the household's. Treating it as spending
    would understate the saving rate and push every projection pessimistic,
    which is the mirror of the optimism this module works to avoid.
    """
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
