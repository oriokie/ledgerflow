"""Builds the `CoachContext` the insight providers reason over.

This module is the only place in the coaching layer that touches the ORM. Every
figure is read through an existing, already-tested selector — budget status,
the cash-flow statement, the cash-flow calendar, goal recommendations, the
health scorer — rather than recomputed here.

That is a deliberate architectural constraint. Reimplementing "how much did
they spend on groceries" inside the coach would create a second source of truth
that drifts from the one the rest of the product shows, and a coach that
disagrees with the dashboard is worse than no coach.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from apps.budgeting import selectors as budget_selectors
from apps.budgeting.models import Budget
from apps.finance import selectors as finance_selectors
from apps.finance.cashflow_calendar import cashflow_calendar
from apps.finance.models import AccountType, FinancialAccount, RecurringTransaction, RecurringType
from apps.goals import recommendations as goal_recommendations

from .protocols import CoachContext

#: Window for "recent" transaction observations.
LOOKBACK_DAYS = 60

#: A transaction at or above this share of the monthly baseline is "large".
#: Relative, not absolute, so it means the same at any income level.
LARGE_PURCHASE_FRACTION = 0.15

#: Minimum change in a recurring merchant charge worth mentioning. Below this,
#: it's noise — and a coach that flags a 2% price rise trains users to ignore it.
MERCHANT_CHANGE_THRESHOLD = 0.10

#: Same for income. Higher, because pay varies for benign reasons (overtime,
#: a five-week month) and a false salary-cut alarm is genuinely alarming.
INCOME_CHANGE_THRESHOLD = 0.15


def _monthly_baseline_minor(currency: str) -> int:
    """Typical monthly outflow — the scale everything else is judged against.

    Zero when there isn't enough history, which the scorer treats as "no
    magnitude points" rather than dividing by it.
    """
    statement = finance_selectors.cashflow_statement(months=6)
    if statement is None or not statement.rows:
        return 0
    outflows = [abs(r.outflow_minor) for r in statement.rows if r.outflow_minor]
    return sum(outflows) // len(outflows) if outflows else 0


def _budget_period_end(budget: Budget) -> date:
    """Last day covered by a budget, derived from its period length.

    Budget stores only `starts_on`; the end is implied. Deriving it here (rather
    than storing it) keeps a single source of truth, and the insight uses it as
    an expiry — an overspend warning about last month stops being actionable
    once the month turns.
    """
    from dateutil.relativedelta import relativedelta

    step = {
        "weekly": relativedelta(weeks=1),
        "monthly": relativedelta(months=1),
        "quarterly": relativedelta(months=3),
        "yearly": relativedelta(years=1),
    }.get(budget.period, relativedelta(months=1))
    return budget.starts_on + step - timedelta(days=1)


def _budget_lines(as_of: date) -> tuple[dict, ...]:
    # Budget stores `starts_on` + a period length, not an explicit end date.
    budget = Budget.objects.filter(is_active=True, starts_on__lte=as_of).order_by("-starts_on").first()
    if budget is None:
        return ()
    lines = budget_selectors.budget_status(budget, as_of=as_of)
    return tuple(
        {
            "category_id": str(line.category_id) if line.category_id else None,
            "category_name": line.category_name,
            # Effective limit includes any rollover, which is the figure the
            # user is actually judged against.
            "limit_minor": line.effective_limit_minor,
            "spent_minor": line.actual_minor,
            "percent": (
                round(line.actual_minor / line.effective_limit_minor * 100, 1)
                if line.effective_limit_minor > 0
                else 0.0
            ),
            "period_end": _budget_period_end(budget),
        }
        for line in lines
    )


def _category_trends(as_of: date) -> tuple[dict, ...]:
    """This month's category spend against last month's."""
    this_start = as_of.replace(day=1)
    last_start = (this_start - timedelta(days=1)).replace(day=1)

    def spend(start: date, end: date) -> dict[str, tuple[str, int]]:
        rows = finance_selectors.category_breakdown(
            start=timezone.make_aware(timezone.datetime.combine(start, timezone.datetime.min.time())),
            end=timezone.make_aware(timezone.datetime.combine(end, timezone.datetime.min.time())),
            expense=True,
        )
        return {str(r.category_id): (r.category_name, r.amount_minor) for r in rows if r.category_id}

    current = spend(this_start, as_of + timedelta(days=1))
    previous = spend(last_start, this_start)

    out: list[dict] = []
    for cat_id, (name, current_minor) in current.items():
        previous_minor = previous.get(cat_id, (name, 0))[1]
        if previous_minor <= 0:
            continue
        delta = (current_minor - previous_minor) / previous_minor
        out.append(
            {
                "category_id": cat_id,
                "category_name": name,
                "current_minor": current_minor,
                "previous_minor": previous_minor,
                "delta_pct": round(delta, 3),
            }
        )
    return tuple(out)


def _large_transactions(as_of: date, baseline_minor: int) -> tuple[dict, ...]:
    if baseline_minor <= 0:
        return ()
    threshold = int(baseline_minor * LARGE_PURCHASE_FRACTION)
    since = as_of - timedelta(days=LOOKBACK_DAYS)
    txns = (
        finance_selectors.list_transactions()
        .filter(occurred_at__date__gte=since, amount_minor__lte=-threshold)
        .select_related("payee")[:20]
    )
    return tuple(
        {
            "transaction_id": str(t.id),
            "payee": getattr(t.payee, "name", "") or t.memo or "Unknown",
            "amount_minor": abs(t.amount_minor),
            "occurred_on": t.occurred_at.date(),
        }
        for t in txns
    )


def _possible_duplicates(as_of: date) -> tuple[dict, ...]:
    """Same payee and amount on the same day, more than once.

    Deliberately conservative. A genuine duplicate is common enough to be worth
    catching, but two identical coffees on one day are also normal — so this
    reports a *candidate* for the user to judge, and the insight wording says
    so rather than asserting an error.
    """
    since = as_of - timedelta(days=LOOKBACK_DAYS)
    groups = (
        finance_selectors.list_transactions()
        .filter(occurred_at__date__gte=since, amount_minor__lt=0)
        # Same GROUP BY trap as above — without this every transaction is its
        # own group and no duplicate is ever found.
        .order_by()
        .values("payee_id", "amount_minor", "occurred_at__date")
        .annotate(n=Count("id"))
        .filter(n__gt=1)[:10]
    )
    out: list[dict] = []
    for g in groups:
        if not g["payee_id"]:
            continue
        sample = (
            finance_selectors.list_transactions()
            .filter(
                payee_id=g["payee_id"],
                amount_minor=g["amount_minor"],
                occurred_at__date=g["occurred_at__date"],
            )
            .select_related("payee")
            .first()
        )
        if sample is None:
            continue
        out.append(
            {
                "transaction_id": str(sample.id),
                "payee": getattr(sample.payee, "name", "") or "Unknown",
                "amount_minor": abs(g["amount_minor"]),
                "occurred_on": g["occurred_at__date"],
                "count": g["n"],
            }
        )
    return tuple(out)


def _subscriptions() -> tuple[dict, ...]:
    """Active recurring expenses, with their annualised cost.

    Annualising is the point: £12 a month doesn't feel like a decision, £144 a
    year does.
    """
    templates = RecurringTransaction.objects.filter(
        is_active=True, txn_type=RecurringType.EXPENSE
    ).select_related("category", "payee")

    per_year = {"daily": 365, "weekly": 52, "monthly": 12, "yearly": 1}
    out: list[dict] = []
    for t in templates:
        multiplier = per_year.get(t.frequency, 12) / max(1, t.interval)
        out.append(
            {
                "name": t.memo or getattr(t.payee, "name", "") or "Subscription",
                "amount_minor": t.amount_minor,
                "frequency": t.frequency,
                "annual_minor": int(t.amount_minor * multiplier),
                "category_name": getattr(t.category, "name", "") or "",
                "next_run_on": t.next_run_on,
            }
        )
    return tuple(sorted(out, key=lambda s: -s["annual_minor"]))


def _debts(as_of: date) -> tuple[dict, ...]:
    accounts = FinancialAccount.objects.filter(
        account_type__in=[AccountType.CREDIT_CARD, AccountType.LOAN],
        archived_at__isnull=True,
    ).select_related("ledger_account__balance", "debt_profile")
    out: list[dict] = []
    for account in accounts:
        owed = finance_selectors.account_current_balance_minor(account)
        if owed <= 0:
            continue
        # Terms are optional, so an account without them still appears — it
        # just can't be ranked by cost.
        profile = getattr(account, "debt_profile", None)
        apr = float(profile.effective_apr(as_of)) if profile else 0.0
        out.append(
            {
                "account_id": str(account.id),
                "name": account.name,
                "balance_minor": owed,
                "currency": account.currency,
                "account_type": account.account_type,
                "apr": apr,
                "monthly_interest_minor": (
                    int(owed * apr / 1200) if apr > 0 else 0
                ),
            }
        )
    # Ranked by what each debt *costs*, not by size — that ordering is only
    # possible now that rates are recorded.
    return tuple(sorted(out, key=lambda d: (-d["apr"], -d["balance_minor"])))


def _debt_signals(as_of: date) -> tuple[dict, ...]:
    """Observations from the debt module, ready to become insights.

    The debt app owns this analysis — it has the rate timelines, fees and
    offsets — so the coach adapts its findings rather than recomputing them.
    Duplicating the logic here would let the coach and the debt dashboard
    disagree about the same debt.
    """
    from apps.debt import selectors as debt_selectors

    return tuple(
        {
            "kind": s.kind,
            "severity": s.severity,
            "title": s.title,
            "body": s.body,
            "rationale": s.rationale,
            "dedupe_key": s.dedupe_key,
            "evidence": s.evidence,
            "account_id": s.account_id,
            "action": s.action or {},
        }
        for s in debt_selectors.debt_signals(as_of=as_of)
    )


def _cashflow_risk() -> dict:
    calendar = cashflow_calendar(days=45)
    if calendar is None:
        return {}
    return {
        "currency": calendar.currency,
        "first_negative_on": calendar.first_negative_on,
        "lowest_balance_minor": calendar.lowest_balance_minor,
        "lowest_balance_on": calendar.lowest_balance_on,
        "negative_day_count": calendar.negative_day_count,
    }


def _health() -> dict:
    """The financial health score and its components.

    The scorer and its inputs already existed and were fully tested; the coach
    simply wasn't reading them. Composing rather than recomputing keeps the
    coach's view identical to the health card on the dashboard.
    """
    from .registry import get_health_scorer
    from .selectors import build_health_inputs

    try:
        score = get_health_scorer().score(build_health_inputs())
    except Exception:  # pragma: no cover - scorer is defensive already
        return {}
    return {
        "score": score.score,
        "band": score.band,
        "components": [
            {"name": c.name, "score": c.score, "weight": c.weight, "detail": c.detail}
            for c in score.components
        ],
    }


def _merchant_changes(as_of: date) -> tuple[dict, ...]:
    """Recurring merchants whose typical charge has moved.

    Compares each payee's mean charge over the last 30 days against the 30 days
    before that, and only for payees seen in **both** windows — a merchant with
    no prior history has no "change" to report, and treating a first purchase as
    a price rise is exactly the sort of false alarm that gets a coach muted.

    Single charges are excluded from the baseline: one purchase isn't a
    "typical" amount, so a second, larger one isn't a price increase.
    """
    recent_start = as_of - timedelta(days=30)
    prior_start = as_of - timedelta(days=60)

    def mean_by_payee(start: date, end: date) -> dict:
        rows = (
            finance_selectors.list_transactions()
            .filter(occurred_at__date__gte=start, occurred_at__date__lt=end, amount_minor__lt=0)
            .exclude(payee__isnull=True)
            # Clear the selector's ordering first: Django folds ORDER BY fields
            # into GROUP BY, which would silently return one row per
            # transaction instead of one per payee.
            .order_by()
            .values("payee_id", "payee__name")
            .annotate(total=Sum("amount_minor"), n=Count("id"))
        )
        return {
            str(r["payee_id"]): {
                "name": r["payee__name"],
                "mean": abs(r["total"]) // r["n"],
                "count": r["n"],
            }
            for r in rows
        }

    recent = mean_by_payee(recent_start, as_of + timedelta(days=1))
    prior = mean_by_payee(prior_start, recent_start)

    out: list[dict] = []
    for payee_id, now in recent.items():
        before = prior.get(payee_id)
        # Needs a real baseline: at least two prior charges to call it "typical".
        if before is None or before["count"] < 2 or before["mean"] <= 0:
            continue
        delta = (now["mean"] - before["mean"]) / before["mean"]
        if abs(delta) < MERCHANT_CHANGE_THRESHOLD:
            continue
        out.append(
            {
                "payee": now["name"],
                "previous_minor": before["mean"],
                "current_minor": now["mean"],
                "delta_pct": round(delta, 3),
            }
        )
    return tuple(sorted(out, key=lambda m: -abs(m["delta_pct"]))[:3])


def _income_changes(as_of: date) -> tuple[dict, ...]:
    """Month-on-month change in total income.

    Higher threshold than merchant changes, and deliberately so: pay varies for
    benign reasons — overtime, a five-week month, a bonus — and a false
    "your income dropped" alarm is genuinely alarming. Requires a full prior
    month of history so a part-month never reads as a pay cut.
    """
    this_start = as_of.replace(day=1)
    last_start = (this_start - timedelta(days=1)).replace(day=1)

    # A part-month can't be compared to a whole one.
    if (as_of - this_start).days < 20:
        return ()

    def income_in(start: date, end: date) -> int:
        total = (
            finance_selectors.list_transactions()
            .filter(occurred_at__date__gte=start, occurred_at__date__lt=end, amount_minor__gt=0)
            .aggregate(total=Sum("amount_minor"))["total"]
        )
        return total or 0

    current = income_in(this_start, as_of + timedelta(days=1))
    previous = income_in(last_start, this_start)
    if previous <= 0 or current <= 0:
        return ()

    delta = (current - previous) / previous
    if abs(delta) < INCOME_CHANGE_THRESHOLD:
        return ()
    return (
        {
            "previous_minor": previous,
            "current_minor": current,
            "delta_pct": round(delta, 3),
            "period_start": this_start,
        },
    )


def _savings_rate() -> float | None:
    """Share of inflow kept, or `None` when it can't be measured.

    `None` rather than 0.0 for an empty workspace. A default zero is
    indistinguishable from a measured zero, and would have the coach telling a
    brand-new user with no data at all that they're saving nothing — a claim
    about figures we don't have.
    """
    statement = finance_selectors.cashflow_statement(months=3)
    if statement is None or not statement.rows:
        return None
    inflow = sum(r.inflow_minor for r in statement.rows)
    if inflow <= 0:
        return None
    outflow = sum(r.outflow_minor for r in statement.rows)
    return round(max(0.0, (inflow - outflow) / inflow), 3)


def build_context(*, as_of: date | None = None) -> CoachContext:
    """Assemble everything the coach reasons over, in one pass.

    Each section degrades independently: a workspace with no budget simply has
    an empty `budget_lines`, and the providers skip that family of insight
    rather than inventing one.
    """
    as_of = as_of or timezone.localdate()
    currency = finance_selectors._dominant_liquid_currency() or "USD"
    baseline = _monthly_baseline_minor(currency)

    return CoachContext(
        as_of=as_of,
        currency=currency,
        budget_lines=_budget_lines(as_of),
        category_trends=_category_trends(as_of),
        large_transactions=_large_transactions(as_of, baseline),
        possible_duplicates=_possible_duplicates(as_of),
        subscriptions=_subscriptions(),
        cashflow_risk=_cashflow_risk(),
        goal_suggestions=tuple(
            {
                "kind": r.kind,
                "title": r.title,
                "rationale": r.rationale,
                "suggested_target_minor": r.suggested_target_minor,
                "currency": r.currency,
            }
            for r in goal_recommendations.recommend_goals(limit=2)
        ),
        merchant_changes=_merchant_changes(as_of),
        income_changes=_income_changes(as_of),
        health=_health(),
        debts=_debts(as_of),
        debt_signals=_debt_signals(as_of),
        savings_rate=_savings_rate(),
    )


def monthly_baseline_minor(currency: str) -> int:
    """Public accessor — the scorer needs the same scale the context used."""
    return _monthly_baseline_minor(currency)
