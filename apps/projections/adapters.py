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
from apps.finance.models import AccountType, BillStatus, FinancialAccount, RecurringTransaction, RecurringType
from apps.finance.schedule import amount_in_month, is_periodical, iter_occurrences, monthly_run_rate_minor
from apps.investments import selectors as investment_selectors

from .calculators import MAX_HORIZON_MONTHS
from .engine import CompiledEvent, DebtPosition, FinancialPosition, add_months, project

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


#: Income cadences mapped onto the finance schedule unit × interval. Quarterly
#: and annual are periodical; the rest still convert to a monthly run-rate.
_INCOME_TO_UNIT = {
    "daily": ("daily", 1),
    "weekly": ("weekly", 1),
    "fortnightly": ("weekly", 2),
    "semi_monthly": ("monthly", 1),
    "monthly": ("monthly", 1),
    "quarterly": ("monthly", 3),
    "annual": ("yearly", 1),
}


def _income_unit(frequency: str) -> tuple[str, int] | None:
    return _INCOME_TO_UNIT.get(str(frequency).lower())


def _next_occurrence(
    *,
    anchor: date,
    frequency: str,
    interval: int,
    on_or_after: date,
    ends_on: date | None,
) -> date | None:
    horizon = add_months(on_or_after, MAX_HORIZON_MONTHS)
    for occurs in iter_occurrences(
        anchor=anchor,
        frequency=frequency,
        interval=interval,
        start=on_or_after,
        end=horizon,
        ends_on=ends_on,
    ):
        return occurs
    return None


def _lump_events(
    *,
    label: str,
    amount: int,
    kind: str,
    anchor: date,
    frequency: str,
    interval: int,
    ends_on: date | None,
    as_of: date,
    max_n: int | None = None,
) -> list[CompiledEvent]:
    """One compiled event per occurrence month, at the full block amount.

    Engine month 1 is the calendar month after `as_of`. This month's occurrence
    belongs in the position, not here.
    """
    if amount <= 0:
        return []
    events: list[CompiledEvent] = []
    horizon = add_months(as_of, MAX_HORIZON_MONTHS)
    for occurs in iter_occurrences(
        anchor=anchor,
        frequency=frequency,
        interval=interval,
        start=as_of.replace(day=1),
        end=horizon,
        ends_on=ends_on,
        max_n=max_n,
    ):
        offset = _month_offset(as_of, occurs)
        if offset < 1:
            continue
        if offset > MAX_HORIZON_MONTHS:
            break
        events.append(
            CompiledEvent(
                label=label,
                start_month=offset,
                end_month=offset,
                monthly_income_delta_minor=amount if kind == "income" else 0,
                monthly_expense_delta_minor=amount if kind == "expense" else 0,
                monthly_investment_delta_minor=amount if kind == "invest" else 0,
            )
        )
    return events


def _month_offset(as_of: date, when: date) -> int:
    """Calendar months from `as_of`'s month to `when`'s. 0 is the same month."""
    return (when.year - as_of.year) * 12 + (when.month - as_of.month)


def _continues_past_this_month(ends_on: date | None, as_of: date) -> bool:
    """Engine month 1 is next calendar month. A contract that ends this month
    must not sit in the forward run-rate."""
    if ends_on is None:
        return True
    return _month_offset(as_of, ends_on) >= 1


def _recurring_already_running(rec: RecurringTransaction, as_of: date) -> bool:
    """True when this template belongs in *this* month's promised cashflow.

    Posted occurrences beat the stored `starts_on`. The edit form used to send
    the next due date as `starts_on`, which parked an already-running rent in
    the future and made projections ignore it.
    """
    if rec.occurrences_created > 0:
        return True
    return _month_offset(as_of, rec.starts_on) <= 0


def _recurring_label(rec: RecurringTransaction) -> str:
    memo = (rec.memo or "").strip()
    if memo:
        return memo
    if rec.payee_id and getattr(rec, "payee", None) is not None:
        return rec.payee.name
    if rec.txn_type == RecurringType.INCOME:
        return "Recurring income"
    if rec.txn_type == RecurringType.EXPENSE:
        return "Recurring expense"
    return "Recurring"


def _source_plan_status(view, as_of: date) -> str:
    """`current`, `upcoming`, or `skip` — the same gate for the stack and events."""
    from apps.income.models import Reliability

    if not view.is_active or view.monthly_net_minor is None:
        return "skip"
    if view.reliability == Reliability.IRREGULAR and not view.expected_is_observed:
        return "skip"
    if not _continues_past_this_month(view.ends_on, as_of):
        return "skip"
    if _month_offset(as_of, view.starts_on) > 0:
        return "upcoming"
    return "current"


def _linked_templates_for_sources(source_ids: list[str]) -> set:
    """Posting templates already represented by an income source on the stack."""
    if not source_ids:
        return set()
    from apps.income.models import IncomeSource

    return set(
        IncomeSource.objects.filter(id__in=source_ids)
        .exclude(recurring_transaction_id=None)
        .values_list("recurring_transaction_id", flat=True)
    )


def _scheduled_run_rate(currency: str, as_of: date) -> tuple[int, int, list[CompiledEvent]]:
    """Known forward income and expenses, plus events that start or end them.

    History is what happened; a schedule is what is promised. A salary entered
    last week has not yet reached the median of trailing months, and a lease
    that ends in six months must not be projected as a forty-year rent. Both
    numbers live here so the engine can apply the known plan and drop it when
    it actually stops.

    Linked income sources and their posting templates are the same money —
    counting both would double every paycheck. A template is skipped only when
    its source actually made it onto the plan; an inactive or irregular source
    must not hide a live paycheck.
    """
    from apps.common.tenant_context import get_current_tenant_id
    from apps.income.selectors import source_views

    if get_current_tenant_id() is None:
        return 0, 0, []

    events: list[CompiledEvent] = []
    income = 0
    expenses = 0

    def apply(
        label: str,
        monthly: int,
        kind: str,
        starts_on: date,
        ends_on: date | None,
        *,
        running: bool,
    ) -> None:
        nonlocal income, expenses
        if monthly <= 0:
            return
        if not _continues_past_this_month(ends_on, as_of) and running:
            return
        if ends_on is not None and ends_on < as_of:
            return

        income_delta = monthly if kind == "income" else 0
        expense_delta = monthly if kind == "expense" else 0
        start_offset = 0 if running else _month_offset(as_of, starts_on)
        last_offset = _month_offset(as_of, ends_on) if ends_on is not None else None

        if start_offset > 0:
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

    counted_source_ids: list[str] = []
    for view in source_views(as_of=as_of, currency=currency):
        status = _source_plan_status(view, as_of)
        if status == "skip":
            continue
        counted_source_ids.append(view.source_id)
        unit = _income_unit(view.frequency)
        if unit is not None and is_periodical(*unit):
            events.extend(
                _lump_events(
                    label=view.name,
                    amount=view.expected_net_minor or view.stated_net_minor,
                    kind="income",
                    anchor=view.starts_on,
                    frequency=unit[0],
                    interval=unit[1],
                    ends_on=view.ends_on,
                    as_of=as_of,
                )
            )
            continue
        apply(
            view.name,
            view.monthly_net_minor or 0,
            "income",
            view.starts_on,
            view.ends_on,
            running=status == "current",
        )

    hidden_templates = _linked_templates_for_sources(counted_source_ids)
    templates = RecurringTransaction.objects.filter(
        is_active=True, currency=currency, txn_type__in=[RecurringType.INCOME, RecurringType.EXPENSE]
    ).select_related("payee")
    for template in templates:
        if template.id in hidden_templates:
            continue
        if not _continues_past_this_month(template.ends_on, as_of) and _recurring_already_running(
            template, as_of
        ):
            continue
        if template.ends_on is not None and template.ends_on < as_of:
            continue
        kind = "income" if template.txn_type == RecurringType.INCOME else "expense"
        remaining = None
        if template.max_occurrences is not None:
            remaining = max(0, template.max_occurrences - template.occurrences_created)
            if remaining == 0:
                continue
        if is_periodical(template.frequency, template.interval):
            events.extend(
                _lump_events(
                    label=_recurring_label(template),
                    amount=template.amount_minor,
                    kind=kind,
                    anchor=template.next_run_on,
                    frequency=template.frequency,
                    interval=template.interval,
                    ends_on=template.ends_on,
                    as_of=as_of,
                    max_n=remaining,
                )
            )
            continue
        monthly = monthly_run_rate_minor(template.amount_minor, template.frequency, template.interval)
        apply(
            _recurring_label(template),
            monthly,
            kind,
            template.starts_on,
            template.ends_on,
            running=_recurring_already_running(template, as_of),
        )

    from apps.finance.models import Bill

    for bill in Bill.objects.filter(
        currency=currency,
        status__in=[BillStatus.UPCOMING, BillStatus.OVERDUE],
    ).exclude(recurrence_frequency=""):
        if not is_periodical(bill.recurrence_frequency, bill.recurrence_interval):
            continue
        events.extend(
            _lump_events(
                label=bill.name,
                amount=bill.amount_minor,
                kind="expense",
                anchor=bill.due_on,
                frequency=bill.recurrence_frequency,
                interval=bill.recurrence_interval,
                ends_on=None,
                as_of=as_of,
            )
        )

    investment_ids = set(
        FinancialAccount.objects.filter(
            account_type=AccountType.INVESTMENT, archived_at__isnull=True
        ).values_list("id", flat=True)
    )
    if investment_ids:
        for recurring in RecurringTransaction.objects.filter(
            is_active=True, txn_type=RecurringType.TRANSFER, currency=currency
        ):
            if recurring.counter_account_id not in investment_ids:
                continue
            if not is_periodical(recurring.frequency, recurring.interval):
                continue
            events.extend(
                _lump_events(
                    label=_recurring_label(recurring),
                    amount=recurring.amount_minor,
                    kind="invest",
                    anchor=recurring.next_run_on,
                    frequency=recurring.frequency,
                    interval=recurring.interval,
                    ends_on=recurring.ends_on,
                    as_of=as_of,
                )
            )

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


_HOUSING_MARKERS = ("rent", "lease", "housing", "landlord", "mortgage")


def _looks_like_housing(label: str) -> bool:
    lowered = label.lower()
    return any(marker in lowered for marker in _HOUSING_MARKERS)


def _stack_line(
    *,
    line_id: str,
    kind: str,
    direction: str,
    label: str,
    monthly_minor: int,
    current: bool,
    starts_on: date | None = None,
    stoppable: bool = False,
    periodical: bool = False,
) -> dict:
    return {
        "id": line_id,
        "kind": kind,
        "direction": direction,
        "label": label,
        "monthly_minor": monthly_minor,
        "current": current,
        "starts_on": starts_on.isoformat() if starts_on is not None and not current else None,
        "stoppable": stoppable,
        "periodical": periodical,
    }


def cashflow_stack(*, currency: str, as_of: date) -> list[dict]:
    """Named scheduled flows that feed the projection, plus a residual.

    Every line is something already on the books: an income source, a
    recurring template, or a repeating bill. Irregular income is omitted
    rather than drawn as a smooth line. The residual is measured history
    minus those schedules so groceries are not double-counted with rent.

    Upcoming schedules stay on the list so a person can see them, but they
    are not part of this month's run-rate (`current=False`).
    """
    from apps.finance.models import Bill
    from apps.income.selectors import source_views

    lines: list[dict] = []
    counted_source_ids: list[str] = []

    for view in source_views(as_of=as_of, currency=currency):
        status = _source_plan_status(view, as_of)
        if status == "skip":
            continue
        counted_source_ids.append(view.source_id)
        unit = _income_unit(view.frequency)
        periodical = unit is not None and is_periodical(*unit)
        if periodical:
            block = view.expected_net_minor or view.stated_net_minor
            due_this_month = (
                amount_in_month(
                    amount_minor=block,
                    frequency=unit[0],
                    interval=unit[1],
                    anchor=view.starts_on,
                    as_of=as_of,
                    ends_on=view.ends_on,
                )
                > 0
            )
            next_on = _next_occurrence(
                anchor=view.starts_on,
                frequency=unit[0],
                interval=unit[1],
                on_or_after=as_of,
                ends_on=view.ends_on,
            )
            lines.append(
                _stack_line(
                    line_id=f"income:{view.source_id}",
                    kind="income",
                    direction="in",
                    label=view.name,
                    monthly_minor=block,
                    current=status == "current" and due_this_month,
                    starts_on=next_on or view.starts_on,
                    periodical=True,
                )
            )
            continue
        lines.append(
            _stack_line(
                line_id=f"income:{view.source_id}",
                kind="income",
                direction="in",
                label=view.name,
                monthly_minor=view.monthly_net_minor or 0,
                current=status == "current",
                starts_on=view.starts_on,
            )
        )

    hidden_templates = _linked_templates_for_sources(counted_source_ids)
    recurring_rows = RecurringTransaction.objects.filter(is_active=True, currency=currency).select_related(
        "payee"
    )
    for recurring in recurring_rows:
        if recurring.id in hidden_templates:
            continue
        if recurring.txn_type == RecurringType.TRANSFER:
            continue
        if recurring.ends_on is not None and recurring.ends_on < as_of:
            continue
        running = _recurring_already_running(recurring, as_of)
        if running and not _continues_past_this_month(recurring.ends_on, as_of):
            continue
        periodical = is_periodical(recurring.frequency, recurring.interval)
        if periodical:
            monthly = recurring.amount_minor
            due_this_month = (
                amount_in_month(
                    amount_minor=recurring.amount_minor,
                    frequency=recurring.frequency,
                    interval=recurring.interval,
                    anchor=recurring.next_run_on,
                    as_of=as_of,
                    ends_on=recurring.ends_on,
                )
                > 0
            )
            current = running and due_this_month
            next_on = _next_occurrence(
                anchor=recurring.next_run_on,
                frequency=recurring.frequency,
                interval=recurring.interval,
                on_or_after=as_of,
                ends_on=recurring.ends_on,
            )
            starts_on = next_on or recurring.starts_on
        else:
            monthly = monthly_run_rate_minor(recurring.amount_minor, recurring.frequency, recurring.interval)
            current = running
            starts_on = recurring.starts_on
        if monthly <= 0:
            continue
        direction = "in" if recurring.txn_type == RecurringType.INCOME else "out"
        label = _recurring_label(recurring)
        lines.append(
            _stack_line(
                line_id=f"recurring:{recurring.id}",
                kind="recurring",
                direction=direction,
                label=label,
                monthly_minor=monthly,
                current=current,
                starts_on=starts_on,
                stoppable=direction == "out" and _looks_like_housing(label),
                periodical=periodical,
            )
        )

    for bill in Bill.objects.filter(
        currency=currency,
        status__in=[BillStatus.UPCOMING, BillStatus.OVERDUE],
    ).exclude(recurrence_frequency=""):
        periodical = is_periodical(bill.recurrence_frequency, bill.recurrence_interval)
        if periodical:
            monthly = bill.amount_minor
            current = (
                amount_in_month(
                    amount_minor=bill.amount_minor,
                    frequency=bill.recurrence_frequency,
                    interval=bill.recurrence_interval,
                    anchor=bill.due_on,
                    as_of=as_of,
                )
                > 0
            )
            next_on = _next_occurrence(
                anchor=bill.due_on,
                frequency=bill.recurrence_frequency,
                interval=bill.recurrence_interval,
                on_or_after=as_of,
                ends_on=None,
            )
        else:
            monthly = monthly_run_rate_minor(
                bill.amount_minor, bill.recurrence_frequency, bill.recurrence_interval
            )
            current = True
            next_on = None
        if monthly <= 0:
            continue
        label = bill.name
        lines.append(
            _stack_line(
                line_id=f"bill:{bill.id}",
                kind="bill",
                direction="out",
                label=label,
                monthly_minor=monthly,
                current=current,
                starts_on=next_on,
                stoppable=_looks_like_housing(label),
                periodical=periodical,
            )
        )

    hist_in, hist_out = _monthly_flows(currency, as_of)
    scheduled_in = sum(
        line["monthly_minor"] for line in lines if line["direction"] == "in" and line["current"]
    )
    scheduled_out = sum(
        line["monthly_minor"] for line in lines if line["direction"] == "out" and line["current"]
    )
    residual_in = max(0, hist_in - scheduled_in)
    residual_out = max(0, hist_out - scheduled_out)
    if residual_in:
        lines.append(
            _stack_line(
                line_id="residual:in",
                kind="residual",
                direction="in",
                label="Unscheduled income (measured)",
                monthly_minor=residual_in,
                current=True,
            )
        )
    if residual_out:
        lines.append(
            _stack_line(
                line_id="residual:out",
                kind="residual",
                direction="out",
                label="Unscheduled spending (measured)",
                monthly_minor=residual_out,
                current=True,
            )
        )
    return lines


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
    stack = cashflow_stack(currency=currency, as_of=as_of)
    income = sum(
        line["monthly_minor"] for line in stack if line["direction"] == "in" and line.get("current", True)
    )
    expenses = sum(
        line["monthly_minor"] for line in stack if line["direction"] == "out" and line.get("current", True)
    )
    if income == 0 and expenses == 0:
        income, expenses = _monthly_flows(currency, as_of)
    debts = _debt_positions(currency)
    # Debt service is applied by the engine from `debts`, so any of it already
    # sitting in the expense stack would be counted twice.
    expenses = max(0, expenses - sum(d.monthly_payment_minor for d in debts))
    contribution = _monthly_investment_contribution_minor(currency, as_of)

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


def _monthly_investment_contribution_minor(currency: str, as_of: date) -> int:
    """Recurring transfers into investment accounts.

    Counted separately from expenses because they are not consumption — money
    moved into a brokerage is still the household's. Treating it as spending
    would understate the saving rate and push every projection pessimistic,
    which is the mirror of the optimism this module works to avoid.

    Periodical standing orders (quarterly, yearly) contribute the full block
    in the month they run, not a twelfth of it every month.
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
        if recurring.counter_account_id not in investment_ids:
            continue
        total += amount_in_month(
            amount_minor=recurring.amount_minor,
            frequency=recurring.frequency,
            interval=recurring.interval,
            anchor=recurring.next_run_on,
            as_of=as_of,
            ends_on=recurring.ends_on,
        )
    return total
