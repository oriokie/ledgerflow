"""Composing selectors — assemble model-free provider inputs from real reads.

The providers are pure functions over DTOs; these selectors are the ONLY place
that turns live engine data (budget status, cash flow, balances, transactions)
into those DTOs. Keeping the mapping here means the providers stay testable and
swappable, and the "what data feeds the AI" question has one auditable answer.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.db import models
from django.db.models import Sum
from django.utils import timezone

from apps.budgeting.models import Budget
from apps.budgeting.selectors import budget_status
from apps.finance.models import Transaction

# `_COUNTED` (posted + reconciled) is the finance layer's own definition of a
# transaction that counts toward reported figures. Imported rather than
# restated so this module cannot drift from it.
from apps.finance.selectors import (
    _COUNTED,
    _NOT_TRANSFER,
    _dominant_liquid_currency,
    cash_flow,
    net_worth,
)
from apps.ledger.models import AccountBalance

from .protocols import AmountObservation, CashflowPoint, HealthInputs, RecommendationContext


def _month_bounds(as_of: date) -> tuple[datetime, datetime]:
    """[start-of-month, as_of end-of-day) as aware datetimes for cash_flow."""
    start = datetime.combine(as_of.replace(day=1), time.min)
    end = datetime.combine(as_of, time.max)
    tz = timezone.get_current_timezone()
    return timezone.make_aware(start, tz), timezone.make_aware(end, tz)


def _income_expense(as_of: date) -> tuple[int, int]:
    """Total income and (positive) expense this month across currencies.

    NOTE: sums across currencies without FX — acceptable for a ratio/rate on a
    predominantly single-currency tenant, which is the current product reality;
    the FX consolidation layer is the documented seam for multi-currency."""
    start, end = _month_bounds(as_of)
    income = 0
    expense = 0
    for flow in cash_flow(start=start, end=end):
        income += flow.income_minor
        expense += abs(flow.expense_minor)  # expense_minor is signed negative
    return income, expense


def build_recommendation_context(*, as_of: date | None = None) -> RecommendationContext:
    """Assemble the recommender's input from current budgets and cash flow."""
    as_of = as_of or timezone.localdate()

    over_budget_lines: list[dict] = []
    underspent_lines: list[dict] = []
    for budget in Budget.objects.all():
        for line in budget_status(budget, as_of=as_of):
            if line.over_budget:
                over_budget_lines.append(
                    {
                        "line_id": line.line_id,
                        "name": line.category_name,
                        "overage_minor": line.actual_minor - line.effective_limit_minor,
                    }
                )
            elif line.remaining_minor > 0:
                underspent_lines.append(
                    {
                        "line_id": line.line_id,
                        "name": line.category_name,
                        "remaining_minor": line.remaining_minor,
                    }
                )

    income, expense = _income_expense(as_of)
    savings_rate = round((income - expense) / income, 3) if income > 0 else 0.0

    return RecommendationContext(
        over_budget_lines=tuple(over_budget_lines),
        underspent_lines=tuple(underspent_lines),
        upcoming_bills=_upcoming_bills_dtos(),  # now backed by the Bill model
        savings_rate=savings_rate,
    )


#: Trailing window, in whole months, for the rate-style health inputs.
#:
#: Whole months, and never the current one. Month-to-date was the single
#: biggest distortion in the old score: on the 2nd of the month a household has
#: banked its salary and paid almost nothing, so "income minus spending over
#: income" read as a ~100% savings rate every month, then sank as the month
#: wore on. A rate has to be measured over periods that have actually finished.
HEALTH_WINDOW_MONTHS = 3

#: Fewest expense transactions in the window before the spending side is
#: considered measured at all. One stray coffee does not establish what a
#: household spends, and a savings rate computed against it would be a
#: near-perfect score derived from a single row.
MIN_EXPENSE_TXNS_FOR_RATE = 3


def _completed_window(as_of: date, months: int) -> tuple[datetime, datetime]:
    """[start, end) covering the `months` whole months before `as_of`'s month."""
    end_date = as_of.replace(day=1)
    start_date = end_date
    for _ in range(months):
        start_date = _prev_month_first(start_date)
    tz = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(start_date, time.min), tz),
        timezone.make_aware(datetime.combine(end_date, time.min), tz),
    )


def build_health_inputs(*, as_of: date | None = None) -> HealthInputs:
    """Assemble the health scorer's five inputs from balances, budgets, cash flow.

    Deterministic and explainable — each input traces to a real read, and any
    input the data cannot support comes back as None rather than as a default
    that reads like a pass. See `HealthInputs` for why that matters.
    """
    as_of = as_of or timezone.localdate()
    start, end = _completed_window(as_of, HEALTH_WINDOW_MONTHS)

    income = 0
    expense = 0
    for flow in cash_flow(start=start, end=end):
        income += flow.income_minor
        expense += abs(flow.expense_minor)  # expense_minor is signed negative

    expense_txns = Transaction.objects.filter(
        _COUNTED, transfer_group__isnull=True, amount_minor__lt=0, occurred_at__gte=start, occurred_at__lt=end
    ).count()
    spending_measured = expense_txns >= MIN_EXPENSE_TXNS_FOR_RATE

    # Savings rate needs both halves: income to divide by, and enough spending
    # on record for "what was left over" to mean anything. Income with no
    # recorded spending is an incomplete picture, not a household that saved
    # everything.
    savings_rate = (
        round(max(0.0, (income - expense) / income), 3) if income > 0 and spending_measured else None
    )

    # assets vs liabilities from the materialized balances in ONE aggregate
    # query (was a per-account loop — an N+1 on the dashboard's hot path).
    assets = 0
    liabilities = 0
    for nw in net_worth():
        assets += nw.assets_minor
        liabilities += nw.liabilities_minor
    if assets <= 0 and liabilities <= 0:
        debt_to_asset = None  # nothing on either side; no balance sheet to read
    elif assets <= 0:
        debt_to_asset = 1.0  # owes money against no assets — genuinely the worst case
    else:
        debt_to_asset = round(liabilities / assets, 3)

    # Emergency runway: months of *typical* spend covered by cash that can
    # actually be reached. Two corrections to what this used to be — it counted
    # every asset including investments and property, and it divided by
    # `expense or 1`, so a household with no recorded spending scored infinite
    # runway and full marks.
    if spending_measured and expense > 0:
        monthly_expense = expense / HEALTH_WINDOW_MONTHS
        liquid = _liquid_assets_minor()
        coverage_months = round(max(0, liquid) / monthly_expense, 1)
    else:
        coverage_months = None

    # Budget adherence: share of lines within limit. No budgets means nothing
    # to keep to — not perfect adherence.
    within = 0
    total = 0
    for budget in Budget.objects.all():
        for line in budget_status(budget, as_of=as_of):
            total += 1
            if not line.over_budget:
                within += 1
    adherence = round(within / total, 3) if total else None

    return HealthInputs(
        savings_rate=savings_rate,
        essential_coverage_months=coverage_months,
        budget_adherence=adherence,
        debt_to_asset=debt_to_asset,
        income_stability=_income_stability(as_of),
    )


def _liquid_assets_minor() -> int:
    """Cash reachable this week, across currencies.

    An emergency fund is money you can spend on Tuesday. A pension, a house and
    an index fund are assets but they are not a runway, and counting them was
    what let a household with nothing set aside score full marks here.

    Sums across currencies without FX, consistent with the other ratio inputs
    (see `cash_flow`'s note) — the FX layer is the documented seam.
    """
    from apps.finance.selectors import _LIQUID_TYPES

    total = AccountBalance.objects.filter(
        account__financial_account__is_active=True,
        account__financial_account__account_type__in=_LIQUID_TYPES,
    ).aggregate(total=models.Sum("balance_minor"))["total"]
    return total or 0


def build_amount_observations(*, days: int = 120) -> list[AmountObservation]:
    """Recent transactions as anomaly observations (expenses only; transfers
    excluded — moving money isn't spending)."""
    since = timezone.now() - timedelta(days=days)
    rows = (
        Transaction.objects.filter(
            _COUNTED,
            _NOT_TRANSFER,
            occurred_at__gte=since,
            amount_minor__lt=0,
        )
        .select_related("payee")
        .order_by("occurred_at")
    )
    observations = []
    for txn in rows:
        payee_name = txn.payee.normalized_name if txn.payee_id else (txn.memo or "unknown")
        observations.append(
            AmountObservation(
                transaction_id=str(txn.id),
                payee_normalized=payee_name,
                category_id=str(txn.category_id) if txn.category_id else None,
                amount_minor=txn.amount_minor,
                occurred_at=txn.occurred_at,
            )
        )
    return observations


# --------------------------------------------------------------- helpers


def _income_stability(as_of: date) -> float | None:
    """1 - coefficient of variation of the last 3 months' income, clamped to 0..1.

    Steady income -> near 1; erratic -> near 0. None when fewer than two of
    those months carried any income at all: variance over one observation is
    not "perfectly stable", it is unmeasured, and returning 1.0 for it credited
    brand-new workspaces with the steadiest income in the product.
    """
    import statistics

    monthly = []
    cursor = as_of.replace(day=1)
    for _ in range(3):
        prev_end = cursor
        prev_start = (cursor - timedelta(days=1)).replace(day=1)
        start_dt = timezone.make_aware(datetime.combine(prev_start, time.min))
        end_dt = timezone.make_aware(datetime.combine(prev_end, time.min))
        qs = Transaction.objects.filter(
            _COUNTED,
            _NOT_TRANSFER,
            occurred_at__gte=start_dt,
            occurred_at__lt=end_dt,
            amount_minor__gt=0,
        )
        currency = _dominant_liquid_currency()
        if currency:
            qs = qs.filter(currency=currency)
        agg = qs.aggregate(total=Sum("amount_minor"))
        monthly.append(agg["total"] or 0)
        cursor = prev_start

    earning_months = [m for m in monthly if m > 0]
    if len(earning_months) < 2:
        return None
    mean = statistics.fmean(monthly)
    if mean == 0:
        return None
    cv = statistics.pstdev(monthly) / mean
    return round(max(0.0, min(1.0, 1 - cv)), 3)


def _prev_month_first(d: date) -> date:
    """First day of the month before `d`'s month."""
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def build_cashflow_history(*, months: int = 6, as_of: date | None = None) -> list[CashflowPoint]:
    """Trailing per-month income/expense series, oldest first — the forecaster's
    input. One grouped query per month over the non-transfer partial index;
    `months` is small (single digits) so this is a handful of cheap aggregates,
    not an N+1 over transactions.

    Counts the same rows as `cash_flow()`: posted/reconciled, non-transfer,
    in the dominant liquid currency. Voided June income must not linger on
    the chart after the ledger list has hidden it.
    """
    as_of = as_of or timezone.localdate()
    currency = _dominant_liquid_currency()
    points: list[CashflowPoint] = []
    month_start = as_of.replace(day=1)
    starts: list[date] = []
    for _ in range(months):
        starts.append(month_start)
        month_start = _prev_month_first(month_start)
    for start in reversed(starts):  # oldest first
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        start_dt = timezone.make_aware(datetime.combine(start, time.min))
        end_dt = timezone.make_aware(datetime.combine(nxt, time.min))
        qs = Transaction.objects.filter(
            _COUNTED,
            _NOT_TRANSFER,
            occurred_at__gte=start_dt,
            occurred_at__lt=end_dt,
        )
        if currency:
            qs = qs.filter(currency=currency)
        agg = qs.aggregate(
            income=Sum("amount_minor", filter=models.Q(amount_minor__gt=0)),
            expense=Sum("amount_minor", filter=models.Q(amount_minor__lt=0)),
        )
        income = agg["income"] or 0
        # Remaining /income paydays belong in this month's bar. A completed
        # month is record, and inventing a salary that never posted would
        # disagree with the ledger.
        if currency and start.year == as_of.year and start.month == as_of.month:
            from apps.income.selectors import scheduled_income_minor

            income += scheduled_income_minor(
                currency=currency,
                start=as_of,
                end=nxt - timedelta(days=1),
            )
        points.append(
            CashflowPoint(
                period_start=start,
                income_minor=income,
                expense_minor=abs(agg["expense"] or 0),
            )
        )
    return points


def net_worth_history(*, months: int = 12, as_of: date | None = None) -> list[dict]:
    """Net-worth as a dated monthly series.

    Today's figure is the materialized position (opening balances, voids and
    all). Earlier months are that position walked backwards through counted
    activity, so voiding a transaction and the opening-balance journal — neither
    of which is a remaining Transaction row — cannot make the chart disagree
    with the headline.

    Owned assets — a house, a car — cannot be reconstructed from postings.
    They are **interpolated between valuations** instead, and never extrapolated
    past the last one. See `assets.selectors.value_at`.
    """
    from apps.assets import selectors as asset_selectors
    from apps.finance.models import FinancialAccount
    from apps.finance.selectors import _ASSET_TYPES, _COUNTED, _dominant_liquid_currency, net_worth

    as_of = as_of or timezone.localdate()
    currency = _dominant_liquid_currency()
    position = next((n for n in net_worth() if n.currency == currency), None) if currency else None
    assets = position.assets_minor if position else 0
    liabilities = position.liabilities_minor if position else 0

    included = {
        a.id: a.account_type in _ASSET_TYPES
        for a in FinancialAccount.objects.filter(include_in_net_worth=True, archived_at__isnull=True)
    }

    series: list[dict] = []
    month_start = as_of.replace(day=1)
    windows: list[tuple[date, date]] = []
    for _ in range(months):
        nxt = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        windows.append((month_start, nxt))
        month_start = _prev_month_first(month_start)

    asset_values = (
        asset_selectors.total_value_on([nxt - timedelta(days=1) for _, nxt in windows], currency=currency)
        if currency
        else {}
    )

    for start, nxt in windows:  # newest first
        on = nxt - timedelta(days=1)
        owned = asset_values.get(on, 0)
        series.append(
            {
                "as_of": on.isoformat(),
                "assets_minor": assets + owned,
                "liabilities_minor": liabilities,
                "net_minor": assets + owned - liabilities,
                "asset_value_minor": owned,
            }
        )
        if currency is None:
            continue
        rows = (
            Transaction.objects.filter(
                _COUNTED,
                currency=currency,
                financial_account_id__in=included,
                occurred_at__date__gte=start,
                occurred_at__date__lt=nxt,
            )
            .values("financial_account_id")
            .annotate(total=Sum("amount_minor"))
        )
        for row in rows:
            total = row["total"] or 0
            if included.get(row["financial_account_id"]):
                assets -= total
            else:
                liabilities -= -total
    series.reverse()
    return series


def spending_trend(*, months: int = 6, as_of: date | None = None) -> list[dict]:
    """Per-month total expense (positive magnitude), oldest first — the
    dashboard spending-trend chart. Derived from the cashflow history so the
    two charts can never disagree."""
    return [
        {
            "period_start": p.period_start.isoformat(),
            "income_minor": p.income_minor,
            "expense_minor": p.expense_minor,
            "net_minor": p.income_minor - p.expense_minor,
        }
        for p in build_cashflow_history(months=months, as_of=as_of)
    ]


def _due_label(days_until_due: int) -> str:
    """A human phrase for a due date, matching how the Bills page itself
    phrases "due soon" — the recommender's title and the Bills list should
    never disagree about what "due" means for the same bill."""
    if days_until_due < 0:
        return "overdue"
    if days_until_due == 0:
        return "today"
    if days_until_due == 1:
        return "tomorrow"
    return f"in {days_until_due} days"


def _upcoming_bills_dtos(*, within_days: int = 30) -> tuple[dict, ...]:
    """Model-free upcoming-bill snapshot for the recommender. Reads the finance
    Bill model via its selector; kept here so the recommender stays pure.

    Every field here must be one the recommender actually reads — see the
    "action the product can execute" rule in providers/recommend.py. Earlier
    revisions included from_account_id/to_account_id/on_date for a
    "schedule_transfer" action that Bill has no model support for (it's paid
    against a Payee, not transferred between two of the user's own accounts)
    and that the frontend never read regardless — both recommender and
    frontend already treat this as "go to the Bills page," so the DTO now
    only carries what's real: identity, amount, and a due-date phrase.
    """
    from apps.finance.bills import upcoming_bills

    return tuple(
        {
            "bill_id": str(ub.bill.id),
            "name": ub.bill.name,
            "amount_minor": ub.bill.amount_minor,
            "currency": ub.bill.currency,
            "due_on": ub.bill.due_on.isoformat(),
            "days_until_due": ub.days_until_due,
            "due_label": _due_label(ub.days_until_due),
        }
        for ub in upcoming_bills(within_days=within_days)
    )


# ------------------------------------------------------------- cash runway ---

RUNWAY_HEALTHY_MONTHS = 12
RUNWAY_WATCH_MONTHS = 6
RUNWAY_WARNING_MONTHS = 3


def cash_runway(*, as_of: date | None = None) -> dict:
    """Will this workspace run out of cash, and roughly when?

    Factors combined:
      • today's liquid balance (checking + savings + cash, dominant currency)
      • the average monthly net flow over the last 3 *full* months
      • bills coming due in the next 30 days (near-term pressure on top of trend)

    If the trend is negative, runway = balance / burn, and the projected
    run-out date is stated plainly. With under two full months of history the
    answer is honestly "insufficient_data" rather than a guess.
    """
    from apps.finance.selectors import _dominant_liquid_currency, liquid_balance_minor

    as_of = as_of or timezone.localdate()
    currency = _dominant_liquid_currency()
    if currency is None:
        return {"status": "insufficient_data", "reason": "no_accounts"}

    balance = liquid_balance_minor(currency)

    # Last 3 *full* months (exclude the in-progress month: partial data skews burn).
    history = build_cashflow_history(months=4, as_of=as_of)[:-1]
    active_months = [p for p in history if p.income_minor or p.expense_minor]
    if len(active_months) < 2:
        return {
            "status": "insufficient_data",
            "reason": "not_enough_history",
            "currency": currency,
            "liquid_balance_minor": balance,
        }

    nets = [p.income_minor - p.expense_minor for p in active_months]
    avg_net = sum(nets) // len(nets)

    upcoming = _upcoming_bills_dtos(within_days=30)
    upcoming_total = sum(b["amount_minor"] for b in upcoming)

    result = {
        "currency": currency,
        "liquid_balance_minor": balance,
        "avg_monthly_net_minor": avg_net,
        "months_analyzed": len(active_months),
        "upcoming_bills_minor": upcoming_total,
        "upcoming_bills_count": len(upcoming),
    }

    if avg_net >= 0:
        # Trend is positive; the only near-term risk is a bill wall taller than the balance.
        result["status"] = "critical" if upcoming_total > balance else "healthy"
        result["months_of_runway"] = None
        result["projected_runout_date"] = None
        return result

    burn = -avg_net
    months_left = balance / burn if burn else float("inf")
    runout = as_of + timedelta(days=int(months_left * 30.44))
    result["months_of_runway"] = round(months_left, 1)
    result["projected_runout_date"] = runout.isoformat()
    if months_left < RUNWAY_WARNING_MONTHS:
        result["status"] = "critical"
    elif months_left < RUNWAY_WATCH_MONTHS:
        result["status"] = "warning"
    elif months_left < RUNWAY_HEALTHY_MONTHS:
        result["status"] = "watch"
    else:
        result["status"] = "healthy"
    return result
