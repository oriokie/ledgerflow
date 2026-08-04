"""The Financial Review — the advisor's periodic sit-down, as a document.

What people pay an advisor for is rarely data they lack; it is the quarterly
hour where somebody assembles it: *here is where you stand, here is what
changed, here is what to do next.* Every ingredient of that hour already
exists in this codebase as a selector. This module is the sit-down — it
composes them into one reviewable document and adds nothing of its own.

Deliberately distinct from `Briefing` (narrative prose over the insight
feed): the Review is figures over the engine's own selectors, with each
section traceable to the module that computed it. The two are complementary
— the briefing is the daily note, the review is the document you would
print for the meeting.

Computed live rather than stored: a *completed* period's ledger is stable,
so recomputing is deterministic, and a stored copy would only add a second
source of truth that drifts the day a back-dated transaction lands. The one
thing that does move — the recommended actions — is supposed to move: advice
about the past period should still be advice for *now*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db.models import Sum
from django.utils import timezone

from apps.analytics import fi
from apps.analytics.filters import Period, ReportFilters
from apps.analytics.reports import cash_flow_report, net_worth_report
from apps.finance.models import CategoryKind, Transaction


class ReviewError(Exception):
    """The period is malformed or not yet reviewable."""


@dataclass(frozen=True)
class ReviewPeriod:
    label: str
    start: date
    end: date  # inclusive

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def parse_period(raw: str | None, *, as_of: date | None = None) -> ReviewPeriod:
    """``2026-07`` (a month), ``2026-Q2`` (a quarter), or blank for the last
    complete month.

    Only *completed* periods are reviewable. A review of a month still in
    progress would present half-formed figures with the authority of a
    document, which is worse than waiting — the dashboard already covers the
    present tense.
    """
    as_of = as_of or timezone.localdate()
    current_month_start = as_of.replace(day=1)

    if not raw:
        end = current_month_start - timedelta(days=1)
        start = end.replace(day=1)
        return ReviewPeriod(label=start.strftime("%B %Y"), start=start, end=end)

    raw = raw.strip()
    if "Q" in raw.upper():
        try:
            year_str, quarter_str = raw.upper().split("-Q")
            year, quarter = int(year_str), int(quarter_str)
            if not 1 <= quarter <= 4:
                raise ValueError
        except ValueError:
            raise ReviewError(f"Unrecognised period {raw!r} — use YYYY-MM or YYYY-Qn.") from None
        start = date(year, 3 * (quarter - 1) + 1, 1)
        end_month = 3 * quarter
        end = (
            date(year + 1, 1, 1) - timedelta(days=1)
            if end_month == 12
            else date(year, end_month + 1, 1) - timedelta(days=1)
        )
        label = f"Q{quarter} {year}"
    else:
        try:
            year_str, month_str = raw.split("-")
            start = date(int(year_str), int(month_str), 1)
        except ValueError:
            raise ReviewError(f"Unrecognised period {raw!r} — use YYYY-MM or YYYY-Qn.") from None
        end = (
            date(start.year + 1, 1, 1) - timedelta(days=1)
            if start.month == 12
            else date(start.year, start.month + 1, 1) - timedelta(days=1)
        )
        label = start.strftime("%B %Y")

    if end >= current_month_start:
        raise ReviewError(
            "That period isn't finished — a review presents half-formed figures with "
            "the authority of a document. It becomes available once the period ends."
        )
    return ReviewPeriod(label=label, start=start, end=end)


def _filters(period: ReviewPeriod) -> ReportFilters:
    return ReportFilters(period=Period.CUSTOM, start=period.start, end=period.end)


def _previous(period: ReviewPeriod) -> ReviewPeriod:
    end = period.start - timedelta(days=1)
    start = end - timedelta(days=period.days - 1)
    return ReviewPeriod(label="previous period", start=start, end=end)


def _category_totals(period: ReviewPeriod, currency: str) -> dict[str, dict]:
    rows = (
        Transaction.objects.filter(
            occurred_at__date__gte=period.start,
            occurred_at__date__lte=period.end,
            amount_minor__lt=0,
            currency=currency,
            category__kind=CategoryKind.EXPENSE,
        )
        .values("category_id", "category__name")
        .annotate(total=Sum("amount_minor"))
    )
    return {str(r["category_id"]): {"name": r["category__name"], "spent": -r["total"]} for r in rows}


def _movers(period: ReviewPeriod, currency: str, *, limit: int = 3) -> dict:
    """The categories that moved most against the previous period.

    Absolute deltas, not percentages: a 400% jump in a 500-shilling category
    is trivia, while 8% on housing is the story of the quarter.
    """
    current = _category_totals(period, currency)
    previous = _category_totals(_previous(period), currency)
    deltas = []
    for key in set(current) | set(previous):
        now = current.get(key, {}).get("spent", 0)
        before = previous.get(key, {}).get("spent", 0)
        if now == before:
            continue
        deltas.append(
            {
                "category_id": key,
                "category_name": (current.get(key) or previous.get(key))["name"],
                "current_minor": now,
                "previous_minor": before,
                "delta_minor": now - before,
            }
        )
    deltas.sort(key=lambda d: d["delta_minor"])
    return {"decreases": deltas[:limit], "increases": deltas[-limit:][::-1]}


def _debt_section(period: ReviewPeriod) -> dict | None:
    from apps.debt import selectors as debt_selectors

    views = debt_selectors.debt_views(as_of=period.end)
    if not views:
        return None
    return {
        "count": len(views),
        "total_balance_minor": sum(v.balance_minor for v in views),
        "total_minimums_minor": sum(v.minimum_payment_minor for v in views),
        "debts": [{"name": v.name, "balance_minor": v.balance_minor, "currency": v.currency} for v in views],
    }


def _goals_section(period: ReviewPeriod) -> list[dict]:
    from apps.goals import forecasting
    from apps.goals import selectors as goal_selectors

    out = []
    for goal in goal_selectors.list_goals():
        status = goal_selectors.goal_status(goal)
        out.append(
            {
                "name": goal.name,
                "currency": goal.currency,
                "target_minor": goal.target_minor,
                "saved_minor": status.saved_minor,
                "percent": status.percent,
                "success_probability": forecasting.success_probability(
                    goal, saved_minor=status.saved_minor, as_of=period.end
                ),
            }
        )
    return out


def _subscriptions_section() -> dict | None:
    """The fee audit: what the standing orders cost per year, and which
    recurring merchants raised their prices.

    Annualising is the entire trick — 1,200 a month does not feel like a
    decision, 14,400 a year does. This is the section that makes a review
    feel like it paid for itself, because a cancelled subscription is the
    rare finding that converts to money without any further discipline.

    Price rises reuse the coach's merchant comparison (mean charge, last 30
    days against the 30 before, both-windows-only) rather than re-deriving
    one — two definitions of "price rise" in one product would eventually
    disagree in public.
    """
    from . import coach_context

    subscriptions = coach_context._subscriptions()
    rises = [
        change
        for change in coach_context._merchant_changes(timezone.localdate())
        if change.get("delta_pct", 0) > 0
    ]
    if not subscriptions and not rises:
        return None
    return {
        "count": len(subscriptions),
        "annual_total_minor": sum(s["annual_minor"] for s in subscriptions),
        "top": [
            {
                "name": s["name"],
                "annual_minor": s["annual_minor"],
                "amount_minor": s["amount_minor"],
                "frequency": s["frequency"],
            }
            for s in subscriptions[:5]
        ],
        "price_rises": [
            {
                "payee": change["payee"],
                "previous_minor": change["previous_minor"],
                "current_minor": change["current_minor"],
                "delta_pct": change["delta_pct"],
            }
            for change in rises
        ],
    }


def _fi_section() -> dict | None:
    try:
        projection = fi.project()
    except fi.NotEnoughHistoryError:
        return None
    middle = projection.band[len(projection.band) // 2]
    return {
        "fi_number_minor": projection.fi_number_minor,
        "progress_pct": projection.progress_pct,
        "years": middle.years,
        "around_year": middle.around_year,
        "never_at_current_pace": projection.never_at_current_pace,
        "required_monthly_for_horizon_minor": projection.required_monthly_for_horizon_minor,
    }


def _actions(limit: int = 3) -> list[dict]:
    """The three things to do next — the part of the sit-down people remember.

    Read from the live insight feed rather than recomputed for the period:
    advice about the past period should still be advice for *now*, and the
    feed's own scoring already ranks by how much each item matters.
    """
    from . import coach

    return [
        {
            "title": insight.title,
            "body": insight.body,
            "severity": insight.severity,
            "kind": insight.kind,
        }
        for insight in coach.live_insights(limit=limit)
    ]


@dataclass(frozen=True)
class FinancialReview:
    period: ReviewPeriod
    currency: str
    sections: dict = field(default_factory=dict)


def compose(*, period_raw: str | None = None, as_of: date | None = None) -> FinancialReview:
    period = parse_period(period_raw, as_of=as_of)
    filters = _filters(period)

    net_worth = net_worth_report(filters)
    currency = net_worth.currency
    cash_now = cash_flow_report(filters)
    cash_before = cash_flow_report(_filters(_previous(period)))

    inflow = cash_now.totals.get("inflow_minor", 0)
    outflow = cash_now.totals.get("outflow_minor", 0)
    saved = inflow - outflow
    rate = round(saved / inflow * 100, 1) if inflow > 0 else None
    before_in = cash_before.totals.get("inflow_minor", 0)
    before_out = cash_before.totals.get("outflow_minor", 0)
    rate_before = round((before_in - before_out) / before_in * 100, 1) if before_in > 0 else None

    series = net_worth.series
    opening = series[0]["net_minor"] if series else 0
    closing = series[-1]["net_minor"] if series else 0

    sections = {
        "net_worth": {
            "opening_minor": opening,
            "closing_minor": closing,
            "delta_minor": closing - opening,
            # The report reconstructs history from flows, exact today and
            # approximate backwards; the review inherits that honesty.
            "approximate": True,
        },
        "cashflow": {
            "inflow_minor": inflow,
            "outflow_minor": outflow,
            "saved_minor": saved,
            "savings_rate_pct": rate,
            "previous_savings_rate_pct": rate_before,
        },
        "movers": _movers(period, currency),
        "debt": _debt_section(period),
        "goals": _goals_section(period),
        "subscriptions": _subscriptions_section(),
        "fi": _fi_section(),
        "actions": _actions(),
    }
    return FinancialReview(period=period, currency=currency, sections=sections)
