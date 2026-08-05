"""The fourteen reports, behind one registry.

Every report returns the same `ReportResult` shape. That uniformity is what
makes the platform a platform: export, caching, the API and the frontend
renderer are each written once, and a fifteenth report inherits all of them by
implementing one function.

Reports read through existing finance selectors wherever one exists. Where they
aggregate directly it is because no selector covers that shape — merchant-level
spend, for instance — and those queries are written to be single-pass rather
than per-row, because a dashboard that fans out into N+1 queries is a dashboard
that gets switched off.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.finance import selectors as finance_selectors
from apps.finance.models import (
    RecurringTransaction,
    RecurringType,
    Transaction,
    TransactionSource,
    TransactionStatus,
)

from .filters import ReportFilters


@dataclass(frozen=True, slots=True)
class ReportResult:
    """The one shape every report returns.

    `series` is for anything plotted over time, `rows` for anything tabular,
    `totals` for the headline figures. A report populates whichever it needs;
    the renderer decides what to draw from what is present rather than from a
    per-report special case.
    """

    slug: str
    title: str
    currency: str
    start: date
    end: date
    totals: dict = field(default_factory=dict)
    series: list[dict] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    #: Anything report-specific — comparison windows, thresholds, caveats.
    meta: dict = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """Nothing worth drawing.

        A totals dict of all zeroes counts as empty. Every report populates the
        same keys whether or not there is data behind them, so testing for a
        non-empty dict would call `{"total_spend_minor": 0}` a finding — and
        the client would render "you spent nothing", which is a claim rather
        than an absence.
        """
        if self.series or self.rows:
            return False
        return not any(value for value in self.totals.values() if isinstance(value, (int, float)))


def _aware(value: date, *, end: bool = False) -> datetime:
    """Date to tenant-local datetime, inclusive of the whole end day."""
    moment = time.max if end else time.min
    return timezone.make_aware(datetime.combine(value, moment))


def _currency_for(filters: ReportFilters) -> str:
    return filters.currency or finance_selectors._dominant_liquid_currency() or "USD"


def _scoped_transactions(filters: ReportFilters, start: date, end: date):
    """Posted, non-transfer transactions inside the window, narrowed by filters.

    Only `POSTED` rows count: a pending transaction is a claim about the future,
    and including it would make a report disagree with the account balance it is
    supposed to explain.

    Transfers are excluded for a different reason. Moving money between two
    accounts you already own changes nothing about your position, but it posts
    two legs — one positive, one negative. Counted, they inflate income and
    spending by the same amount, so every report reading this queryset would
    tell a household that diligently moved £500 into savings that it had both
    earned and spent an extra £500. `record_transfer` states this contract, and
    the finance selectors already honour it via `_NOT_TRANSFER`; the reporting
    platform aggregates directly and so has to apply it here.
    """
    qs = Transaction.objects.filter(
        occurred_at__gte=_aware(start),
        occurred_at__lte=_aware(end, end=True),
        status=TransactionStatus.POSTED,
        transfer_group__isnull=True,
    )
    if filters.account_ids:
        qs = qs.filter(financial_account_id__in=filters.account_ids)
    if filters.category_ids:
        qs = qs.filter(category_id__in=filters.category_ids)
    if filters.currency:
        qs = qs.filter(currency=filters.currency)
    # The selector's ordering would leak into GROUP BY on every aggregate
    # below, silently producing one row per transaction.
    return qs.order_by()


def _monthly_totals(filters: ReportFilters, start: date, end: date) -> dict[date, dict]:
    """Income and expense per month, in one query."""
    rows = (
        _scoped_transactions(filters, start, end)
        .annotate(bucket=TruncMonth("occurred_at"))
        .values("bucket")
        .annotate(
            inflow=Sum("amount_minor", filter=Q(amount_minor__gt=0)),
            outflow=Sum("amount_minor", filter=Q(amount_minor__lt=0)),
            count=Count("id"),
        )
    )
    out: dict[date, dict] = {}
    for row in rows:
        bucket = row["bucket"]
        month = bucket.date().replace(day=1) if hasattr(bucket, "date") else bucket
        out[month] = {
            "inflow_minor": row["inflow"] or 0,
            "outflow_minor": abs(row["outflow"] or 0),
            "count": row["count"],
        }
    return out


def _month_range(start: date, end: date) -> list[date]:
    months: list[date] = []
    cursor = start.replace(day=1)
    last = end.replace(day=1)
    while cursor <= last:
        months.append(cursor)
        cursor = (cursor + timedelta(days=32)).replace(day=1)
    return months


# =============================================================================
# Reports
# =============================================================================
def net_worth_report(filters: ReportFilters) -> ReportResult:
    """Assets, liabilities and the gap between them, over time.

    Point-in-time balances aren't stored per day, so the series is reconstructed
    from the current position walked backwards through the period's net flows.
    Approximate for past months and exact for today — stated in `meta` rather
    than presented as a precise history it isn't.
    """
    start, end = filters.window()
    currency = _currency_for(filters)

    positions = {n.currency: n for n in finance_selectors.net_worth()}
    position = positions.get(currency)
    assets = position.assets_minor if position else 0
    liabilities = position.liabilities_minor if position else 0

    monthly = _monthly_totals(filters, start, end)
    months = _month_range(start, end)

    # Walk backwards from today's known position.
    series: list[dict] = []
    running = assets - liabilities
    for month in reversed(months):
        series.append({"month": month, "net_minor": running})
        flows = monthly.get(month, {})
        running -= flows.get("inflow_minor", 0) - flows.get("outflow_minor", 0)
    series.reverse()

    opening = series[0]["net_minor"] if series else 0
    return ReportResult(
        slug="net_worth",
        title="Net worth",
        currency=currency,
        start=start,
        end=end,
        totals={
            "assets_minor": assets,
            "liabilities_minor": liabilities,
            "net_minor": assets - liabilities,
            "change_minor": (assets - liabilities) - opening,
        },
        series=series,
        meta={
            "reconstructed": True,
            "note": (
                "Past months are reconstructed from recorded flows, so they are approximate. "
                "Today's figure is exact."
            ),
        },
    )


def savings_rate_report(filters: ReportFilters) -> ReportResult:
    """What share of income is kept, month by month.

    Months with no income are omitted rather than plotted at zero: a zero
    savings rate means "earned and spent it all", and showing that for a month
    with no recorded income would be a claim about data that doesn't exist.
    """
    start, end = filters.window()
    currency = _currency_for(filters)
    monthly = _monthly_totals(filters, start, end)

    series: list[dict] = []
    total_in = 0
    total_out = 0
    for month in _month_range(start, end):
        flows = monthly.get(month)
        if not flows or flows["inflow_minor"] <= 0:
            continue
        inflow = flows["inflow_minor"]
        outflow = flows["outflow_minor"]
        total_in += inflow
        total_out += outflow
        series.append(
            {
                "month": month,
                "inflow_minor": inflow,
                "outflow_minor": outflow,
                "saved_minor": inflow - outflow,
                "rate": round((inflow - outflow) / inflow * 100, 1),
            }
        )

    overall = round((total_in - total_out) / total_in * 100, 1) if total_in > 0 else None
    return ReportResult(
        slug="savings_rate",
        title="Savings rate",
        currency=currency,
        start=start,
        end=end,
        totals={
            "inflow_minor": total_in,
            "outflow_minor": total_out,
            "saved_minor": total_in - total_out,
            # None, not zero, when there's no income to measure against.
            "rate": overall,
        },
        series=series,
        meta={"months_measured": len(series)},
    )


def cash_flow_report(filters: ReportFilters) -> ReportResult:
    """Money in against money out, by month."""
    start, end = filters.window()
    currency = _currency_for(filters)
    monthly = _monthly_totals(filters, start, end)

    series = []
    for month in _month_range(start, end):
        flows = monthly.get(month, {"inflow_minor": 0, "outflow_minor": 0, "count": 0})
        series.append(
            {
                "month": month,
                "inflow_minor": flows["inflow_minor"],
                "outflow_minor": flows["outflow_minor"],
                "net_minor": flows["inflow_minor"] - flows["outflow_minor"],
                "transaction_count": flows["count"],
            }
        )

    total_in = sum(p["inflow_minor"] for p in series)
    total_out = sum(p["outflow_minor"] for p in series)
    positive = [p for p in series if p["net_minor"] > 0]
    return ReportResult(
        slug="cash_flow",
        title="Cash flow",
        currency=currency,
        start=start,
        end=end,
        totals={
            "inflow_minor": total_in,
            "outflow_minor": total_out,
            "net_minor": total_in - total_out,
            "positive_months": len(positive),
            "total_months": len(series),
        },
        series=series,
    )


def income_sources_report(filters: ReportFilters) -> ReportResult:
    """Where income comes from, and how concentrated it is.

    The concentration figure is the point: someone with 95% of income from one
    source has a different risk profile from someone with four even streams,
    and a plain list of amounts doesn't say that.
    """
    start, end = filters.window()
    currency = _currency_for(filters)

    rows = (
        _scoped_transactions(filters, start, end)
        .filter(amount_minor__gt=0)
        .values("category_id", "category__name", "payee__name")
        .annotate(total=Sum("amount_minor"), count=Count("id"))
        .order_by("-total")[:40]
    )

    buckets: dict[str, dict] = {}
    for row in rows:
        label = row["category__name"] or row["payee__name"] or "Uncategorised"
        bucket = buckets.setdefault(
            label, {"label": label, "amount_minor": 0, "count": 0, "category_id": row["category_id"]}
        )
        bucket["amount_minor"] += row["total"] or 0
        bucket["count"] += row["count"]

    ordered = sorted(buckets.values(), key=lambda b: -b["amount_minor"])
    total = sum(b["amount_minor"] for b in ordered)
    for bucket in ordered:
        bucket["percent"] = round(bucket["amount_minor"] / total * 100, 1) if total else 0.0

    largest_share = ordered[0]["percent"] if ordered else 0.0
    return ReportResult(
        slug="income_sources",
        title="Income sources",
        currency=currency,
        start=start,
        end=end,
        totals={
            "total_minor": total,
            "source_count": len(ordered),
            "largest_share": largest_share,
        },
        rows=ordered,
        meta={
            # Named because it changes what the numbers mean, not just how they
            # look.
            "concentrated": largest_share
            >= 80,
        },
    )


def expense_trends_report(filters: ReportFilters) -> ReportResult:
    """Spending per month, with the direction of travel."""
    start, end = filters.window()
    currency = _currency_for(filters)
    monthly = _monthly_totals(filters, start, end)

    series = [
        {"month": month, "outflow_minor": monthly.get(month, {}).get("outflow_minor", 0)}
        for month in _month_range(start, end)
    ]
    amounts = [p["outflow_minor"] for p in series if p["outflow_minor"] > 0]
    average = sum(amounts) // len(amounts) if amounts else 0

    # Direction from the first and second halves rather than first-vs-last:
    # a single unusual month at either end would otherwise decide the verdict.
    trend = None
    if len(amounts) >= 4:
        midpoint = len(amounts) // 2
        earlier = sum(amounts[:midpoint]) / midpoint
        later = sum(amounts[midpoint:]) / (len(amounts) - midpoint)
        if earlier > 0:
            trend = round((later - earlier) / earlier * 100, 1)

    return ReportResult(
        slug="expense_trends",
        title="Expense trends",
        currency=currency,
        start=start,
        end=end,
        totals={
            "total_minor": sum(amounts),
            "average_minor": average,
            "highest_minor": max(amounts) if amounts else 0,
            "lowest_minor": min(amounts) if amounts else 0,
            "trend_pct": trend,
        },
        series=series,
        meta={"months_measured": len(amounts)},
    )


def merchant_analytics_report(filters: ReportFilters) -> ReportResult:
    """Where the money actually goes, by payee.

    Frequency sits alongside total because they tell different stories: one
    £900 sofa and ninety £10 lunches are the same total and completely
    different problems.
    """
    start, end = filters.window()
    currency = _currency_for(filters)

    rows = (
        _scoped_transactions(filters, start, end)
        .filter(amount_minor__lt=0)
        .exclude(payee__isnull=True)
        .values("payee_id", "payee__name")
        .annotate(total=Sum("amount_minor"), count=Count("id"))
        .order_by("total")[:50]
    )

    merchants = []
    for row in rows:
        spend = abs(row["total"] or 0)
        merchants.append(
            {
                "payee_id": str(row["payee_id"]),
                "label": row["payee__name"],
                "amount_minor": spend,
                "count": row["count"],
                "average_minor": spend // row["count"] if row["count"] else 0,
            }
        )

    total = sum(m["amount_minor"] for m in merchants)
    for merchant in merchants:
        merchant["percent"] = round(merchant["amount_minor"] / total * 100, 1) if total else 0.0

    most_frequent = max(merchants, key=lambda m: m["count"]) if merchants else None
    return ReportResult(
        slug="merchant_analytics",
        title="Merchants",
        currency=currency,
        start=start,
        end=end,
        totals={
            "total_minor": total,
            "merchant_count": len(merchants),
            "most_frequent": most_frequent["label"] if most_frequent else None,
            "most_frequent_count": most_frequent["count"] if most_frequent else 0,
        },
        rows=merchants,
    )


def category_analytics_report(filters: ReportFilters) -> ReportResult:
    """Spending by category, with each one's share."""
    start, end = filters.window()
    currency = _currency_for(filters)

    rows = (
        _scoped_transactions(filters, start, end)
        .filter(amount_minor__lt=0)
        .values("category_id", "category__name")
        .annotate(total=Sum("amount_minor"), count=Count("id"))
        .order_by("total")[:50]
    )

    categories = []
    for row in rows:
        categories.append(
            {
                "category_id": str(row["category_id"]) if row["category_id"] else None,
                "label": row["category__name"] or "Uncategorised",
                "amount_minor": abs(row["total"] or 0),
                "count": row["count"],
            }
        )

    total = sum(c["amount_minor"] for c in categories)
    for category in categories:
        category["percent"] = round(category["amount_minor"] / total * 100, 1) if total else 0.0

    uncategorised = next((c for c in categories if c["category_id"] is None), None)
    return ReportResult(
        slug="category_analytics",
        title="Categories",
        currency=currency,
        start=start,
        end=end,
        totals={
            "total_minor": total,
            "category_count": len([c for c in categories if c["category_id"]]),
            # Surfaced because it caps how much any category report can be
            # trusted, and it's fixable.
            "uncategorised_minor": uncategorised["amount_minor"] if uncategorised else 0,
        },
        rows=categories,
    )


def lifestyle_inflation_report(filters: ReportFilters) -> ReportResult:
    """Whether spending is rising faster than income.

    The single most useful long-run question a finance app can answer, and one
    that neither an income chart nor a spending chart answers alone. A raise
    absorbed entirely by higher spending leaves someone no better off, and only
    the comparison shows it.
    """
    start, end = filters.window()
    currency = _currency_for(filters)
    monthly = _monthly_totals(filters, start, end)
    months = [m for m in _month_range(start, end) if m in monthly]

    if len(months) < 4:
        return ReportResult(
            slug="lifestyle_inflation",
            title="Lifestyle inflation",
            currency=currency,
            start=start,
            end=end,
            meta={
                "insufficient_data": True,
                # Four months is the floor for a half-vs-half comparison to
                # mean anything at all.
                "note": "At least four months of activity are needed to compare periods.",
            },
        )

    midpoint = len(months) // 2

    def totals(subset):
        return (
            sum(monthly[m]["inflow_minor"] for m in subset),
            sum(monthly[m]["outflow_minor"] for m in subset),
        )

    early_in, early_out = totals(months[:midpoint])
    late_in, late_out = totals(months[midpoint:])

    early_months = midpoint or 1
    late_months = len(months) - midpoint or 1
    early_in_avg, early_out_avg = early_in / early_months, early_out / early_months
    late_in_avg, late_out_avg = late_in / late_months, late_out / late_months

    income_growth = round((late_in_avg - early_in_avg) / early_in_avg * 100, 1) if early_in_avg > 0 else None
    spend_growth = (
        round((late_out_avg - early_out_avg) / early_out_avg * 100, 1) if early_out_avg > 0 else None
    )
    gap = (
        round(spend_growth - income_growth, 1)
        if income_growth is not None and spend_growth is not None
        else None
    )

    series = [
        {
            "month": month,
            "inflow_minor": monthly[month]["inflow_minor"],
            "outflow_minor": monthly[month]["outflow_minor"],
        }
        for month in months
    ]

    return ReportResult(
        slug="lifestyle_inflation",
        title="Lifestyle inflation",
        currency=currency,
        start=start,
        end=end,
        totals={
            "income_growth_pct": income_growth,
            "spend_growth_pct": spend_growth,
            # Positive means spending outpaced income — the thing worth knowing.
            "gap_pct": gap,
            "early_spend_avg_minor": int(early_out_avg),
            "late_spend_avg_minor": int(late_out_avg),
        },
        series=series,
        meta={
            "inflating": gap is not None and gap > 5,
            "early_months": early_months,
            "late_months": late_months,
        },
    )


def monthly_comparison_report(filters: ReportFilters) -> ReportResult:
    """This month against last, by category."""
    today = timezone.localdate()
    this_start = today.replace(day=1)
    last_end = this_start - timedelta(days=1)
    last_start = last_end.replace(day=1)
    currency = _currency_for(filters)

    def by_category(start: date, end: date) -> dict[str, int]:
        rows = (
            _scoped_transactions(filters, start, end)
            .filter(amount_minor__lt=0)
            .values("category__name")
            .annotate(total=Sum("amount_minor"))
        )
        return {(r["category__name"] or "Uncategorised"): abs(r["total"] or 0) for r in rows}

    current = by_category(this_start, today)
    previous = by_category(last_start, last_end)

    rows = []
    for label in sorted(set(current) | set(previous)):
        now = current.get(label, 0)
        before = previous.get(label, 0)
        rows.append(
            {
                "label": label,
                "current_minor": now,
                "previous_minor": before,
                "change_minor": now - before,
                # None rather than a fabricated percentage when there is no
                # baseline: "up from nothing" is not a percentage.
                "change_pct": round((now - before) / before * 100, 1) if before > 0 else None,
            }
        )
    rows.sort(key=lambda r: -abs(r["change_minor"]))

    return ReportResult(
        slug="monthly_comparison",
        title="This month vs last",
        currency=currency,
        start=last_start,
        end=today,
        totals={
            "current_minor": sum(current.values()),
            "previous_minor": sum(previous.values()),
            "change_minor": sum(current.values()) - sum(previous.values()),
        },
        rows=rows,
        meta={
            "current_period": this_start.isoformat(),
            "previous_period": last_start.isoformat(),
            # A part-month against a whole one is not a fair comparison, and
            # saying so beats quietly flattering the current month.
            "partial_month": today.day < 28,
        },
    )


def year_over_year_report(filters: ReportFilters) -> ReportResult:
    """This year against last, month by month."""
    today = timezone.localdate()
    currency = _currency_for(filters)

    def year_months(year: int) -> dict[int, dict]:
        start = date(year, 1, 1)
        end = min(date(year, 12, 31), today)
        monthly = _monthly_totals(filters, start, end)
        return {m.month: v for m, v in monthly.items()}

    current = year_months(today.year)
    previous = year_months(today.year - 1)

    series = []
    for month in range(1, 13):
        now = current.get(month, {})
        before = previous.get(month, {})
        series.append(
            {
                "month": month,
                "current_outflow_minor": now.get("outflow_minor", 0),
                "previous_outflow_minor": before.get("outflow_minor", 0),
                "current_inflow_minor": now.get("inflow_minor", 0),
                "previous_inflow_minor": before.get("inflow_minor", 0),
            }
        )

    # Compare only the months that exist in both years, or a part-year would
    # look like a collapse in spending.
    comparable = [m for m in range(1, 13) if m in current and m in previous]
    current_total = sum(current[m]["outflow_minor"] for m in comparable)
    previous_total = sum(previous[m]["outflow_minor"] for m in comparable)

    return ReportResult(
        slug="year_over_year",
        title="Year over year",
        currency=currency,
        start=date(today.year - 1, 1, 1),
        end=today,
        totals={
            "current_outflow_minor": current_total,
            "previous_outflow_minor": previous_total,
            "change_pct": (
                round((current_total - previous_total) / previous_total * 100, 1)
                if previous_total > 0
                else None
            ),
            "comparable_months": len(comparable),
        },
        series=series,
        meta={"current_year": today.year, "previous_year": today.year - 1},
    )


def income_vs_spending_report(filters: ReportFilters) -> ReportResult:
    """The two lines side by side, and where they crossed."""
    start, end = filters.window()
    currency = _currency_for(filters)
    monthly = _monthly_totals(filters, start, end)

    series = []
    deficit_months = 0
    for month in _month_range(start, end):
        flows = monthly.get(month, {"inflow_minor": 0, "outflow_minor": 0})
        net = flows["inflow_minor"] - flows["outflow_minor"]
        if flows["inflow_minor"] > 0 and net < 0:
            deficit_months += 1
        series.append(
            {
                "month": month,
                "inflow_minor": flows["inflow_minor"],
                "outflow_minor": flows["outflow_minor"],
                "net_minor": net,
            }
        )

    total_in = sum(p["inflow_minor"] for p in series)
    total_out = sum(p["outflow_minor"] for p in series)
    return ReportResult(
        slug="income_vs_spending",
        title="Income vs spending",
        currency=currency,
        start=start,
        end=end,
        totals={
            "inflow_minor": total_in,
            "outflow_minor": total_out,
            "net_minor": total_in - total_out,
            # The count that matters more than the total: twelve balanced
            # months and one disaster is a different story from a steady drain.
            "deficit_months": deficit_months,
        },
        series=series,
    )


def largest_purchases_report(filters: ReportFilters) -> ReportResult:
    """The biggest individual outgoings in the window."""
    start, end = filters.window()
    currency = _currency_for(filters)

    transactions = (
        _scoped_transactions(filters, start, end)
        .filter(amount_minor__lt=0)
        .select_related("payee", "category", "financial_account")
        .order_by("amount_minor")[:25]
    )

    rows = [
        {
            "transaction_id": str(t.id),
            "label": getattr(t.payee, "name", "") or t.memo or "Unknown",
            "amount_minor": abs(t.amount_minor),
            "occurred_on": t.occurred_at.date(),
            "category": getattr(t.category, "name", "") or "Uncategorised",
            "account": t.financial_account.name,
        }
        for t in transactions
    ]

    total_spend = (
        _scoped_transactions(filters, start, end)
        .filter(amount_minor__lt=0)
        .aggregate(total=Sum("amount_minor"))["total"]
        or 0
    )
    top_ten = sum(r["amount_minor"] for r in rows[:10])
    return ReportResult(
        slug="largest_purchases",
        title="Largest purchases",
        currency=currency,
        start=start,
        end=end,
        totals={
            "top_ten_minor": top_ten,
            "total_spend_minor": abs(total_spend),
            # How concentrated spending is — often more surprising than the
            # individual amounts.
            "top_ten_share": (round(top_ten / abs(total_spend) * 100, 1) if total_spend else 0.0),
        },
        rows=rows,
    )


def subscription_costs_report(filters: ReportFilters) -> ReportResult:
    """Recurring charges, annualised.

    Annualising is the point: £12 a month doesn't feel like a decision, £144 a
    year does.
    """
    currency = _currency_for(filters)
    start, end = filters.window()

    templates = RecurringTransaction.objects.filter(
        is_active=True, txn_type=RecurringType.EXPENSE, currency=currency
    ).select_related("category", "payee")

    per_year = {"daily": 365, "weekly": 52, "monthly": 12, "yearly": 1}
    rows = []
    for template in templates:
        multiplier = per_year.get(template.frequency, 12) / max(1, template.interval)
        rows.append(
            {
                "label": template.memo or getattr(template.payee, "name", "") or "Subscription",
                "amount_minor": template.amount_minor,
                "frequency": template.frequency,
                "annual_minor": int(template.amount_minor * multiplier),
                "category": getattr(template.category, "name", "") or "Uncategorised",
                "next_on": template.next_run_on,
            }
        )
    rows.sort(key=lambda r: -r["annual_minor"])

    annual_total = sum(r["annual_minor"] for r in rows)
    return ReportResult(
        slug="subscription_costs",
        title="Subscriptions",
        currency=currency,
        start=start,
        end=end,
        totals={
            "annual_minor": annual_total,
            "monthly_minor": annual_total // 12,
            "count": len(rows),
        },
        rows=rows,
    )


def financial_health_report(filters: ReportFilters) -> ReportResult:
    """The health score and its components.

    Delegated to the intelligence app rather than recomputed: a second
    implementation would eventually disagree with the dashboard card, and two
    different health scores is worse than one.
    """
    currency = _currency_for(filters)
    start, end = filters.window()

    from apps.intelligence.registry import get_health_scorer
    from apps.intelligence.selectors import build_health_inputs

    try:
        score = get_health_scorer().score(build_health_inputs())
    except Exception:  # pragma: no cover - scorer is defensive already
        return ReportResult(
            slug="financial_health",
            title="Financial health",
            currency=currency,
            start=start,
            end=end,
            meta={"unavailable": True},
        )

    rows = [
        {
            "label": component.name,
            "score": component.score,
            "weight": component.weight,
            "detail": component.detail,
        }
        for component in score.components
    ]
    # Measured components first, weakest of them at the top; the ones with no
    # basis sort to the end rather than being ranked against real scores. Their
    # `detail` says what is missing, so they read as gaps to fill.
    rows.sort(key=lambda r: (r["score"] is None, r["score"] if r["score"] is not None else 0))
    weakest = next((r["label"] for r in rows if r["score"] is not None), None)

    return ReportResult(
        slug="financial_health",
        title="Financial health",
        currency=currency,
        start=start,
        end=end,
        totals={"score": score.score, "band": score.band, "coverage": score.coverage},
        rows=rows,
        # Weakest first: where an improvement moves the number most.
        meta={"weakest": weakest},
    )


# =============================================================================
# Registry
# =============================================================================
def category_movers_report(filters: ReportFilters) -> ReportResult:
    """Which categories moved most between the last two full months.

    Totals tell you what you spent; movers tell you what *changed*, which is
    the only part you can act on. Ranked by absolute swing so a large drop is
    as visible as a large rise — a category that collapsed is usually either
    good news worth keeping or a bill that hasn't landed yet.
    """
    start, end = filters.window()
    currency = _currency_for(filters)

    today = timezone.localdate()
    this_month = today.replace(day=1)
    last_month = (this_month - timedelta(days=1)).replace(day=1)
    prior_month = (last_month - timedelta(days=1)).replace(day=1)

    def spend_by_category(month_start: date, month_end: date) -> dict:
        rows = (
            _scoped_transactions(filters, month_start, month_end)
            .filter(amount_minor__lt=0)
            .values("category_id", "category__name")
            .annotate(total=Sum("amount_minor"))
        )
        return {
            (str(r["category_id"]) if r["category_id"] else None): {
                "label": r["category__name"] or "Uncategorised",
                "amount_minor": abs(r["total"] or 0),
            }
            for r in rows
        }

    current = spend_by_category(last_month, this_month - timedelta(days=1))
    previous = spend_by_category(prior_month, last_month - timedelta(days=1))

    rows = []
    for key in set(current) | set(previous):
        now = current.get(key, {}).get("amount_minor", 0)
        before = previous.get(key, {}).get("amount_minor", 0)
        if now == 0 and before == 0:
            continue
        label = current.get(key, previous.get(key, {})).get("label", "Uncategorised")
        rows.append(
            {
                "category_id": key,
                "label": label,
                "amount_minor": now,
                "previous_minor": before,
                "change_minor": now - before,
                # A category with no prior spend has no meaningful percentage;
                # None says "new" rather than implying an infinite increase.
                "change_percent": (round((now - before) / before * 100, 1) if before else None),
            }
        )

    rows.sort(key=lambda r: -abs(r["change_minor"]))
    rows = rows[:20]

    increases = [r for r in rows if r["change_minor"] > 0]
    decreases = [r for r in rows if r["change_minor"] < 0]
    return ReportResult(
        slug="category_movers",
        title="What changed",
        currency=currency,
        start=start,
        end=end,
        totals={
            "net_change_minor": sum(r["change_minor"] for r in rows),
            "biggest_rise": increases[0]["label"] if increases else None,
            "biggest_rise_minor": increases[0]["change_minor"] if increases else 0,
            "biggest_fall": decreases[0]["label"] if decreases else None,
            "biggest_fall_minor": decreases[0]["change_minor"] if decreases else 0,
        },
        rows=rows,
        meta={"current_month": last_month, "compared_to": prior_month},
    )


#: Monday-first, matching how most of the world reads a week. Python's
#: `weekday()` already returns 0 for Monday, so no remapping is needed.
_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def spending_by_weekday_report(filters: ReportFilters) -> ReportResult:
    """When in the week money actually leaves.

    Spending has a rhythm most people can't state from memory but recognise
    instantly once drawn. Averaging per occurrence rather than summing is what
    makes it honest: a window holding five Saturdays and four Sundays would
    otherwise make Saturday look 25% heavier for reasons of the calendar.
    """
    start, end = filters.window()
    currency = _currency_for(filters)

    txns = _scoped_transactions(filters, start, end).filter(amount_minor__lt=0)

    totals = [0] * 7
    counts = [0] * 7
    for occurred_at, amount in txns.values_list("occurred_at", "amount_minor"):
        local = timezone.localtime(occurred_at) if timezone.is_aware(occurred_at) else occurred_at
        totals[local.weekday()] += abs(amount)
        counts[local.weekday()] += 1

    # How many of each weekday the window actually contained.
    occurrences = [0] * 7
    cursor = start
    while cursor <= end:
        occurrences[cursor.weekday()] += 1
        cursor += timedelta(days=1)

    weekday_total = sum(totals[:5])
    weekend_total = sum(totals[5:])
    grand = weekday_total + weekend_total

    # Seven zero bars would render as "you spent nothing on every day of the
    # week", which is a claim. The platform's contract is that an absence
    # reports as empty, so the series is withheld rather than fabricated.
    series = (
        [
            {
                "label": _WEEKDAY_LABELS[i],
                "amount_minor": totals[i],
                "average_minor": totals[i] // occurrences[i] if occurrences[i] else 0,
                "count": counts[i],
            }
            for i in range(7)
        ]
        if grand
        else []
    )

    busiest = max(series, key=lambda d: d["average_minor"]) if series else None

    return ReportResult(
        slug="spending_by_weekday",
        title="Spending by day of week",
        currency=currency,
        start=start,
        end=end,
        totals={
            "total_minor": grand,
            "weekday_minor": weekday_total,
            "weekend_minor": weekend_total,
            "weekend_share": round(weekend_total / grand * 100, 1) if grand else 0.0,
            "busiest_day": busiest["label"] if busiest else None,
        },
        series=series,
    )


def committed_vs_discretionary_report(filters: ReportFilters) -> ReportResult:
    """How much of your spending you could actually change this month.

    Two households spending the same amount are in very different positions if
    one owes most of it to standing commitments. Splitting the total answers
    the question a bare figure can't: how much room is there to move?

    "Committed" means posted by a recurring template. That is deliberately
    conservative — a bill paid by hand counts as discretionary here — because
    inferring commitment from a payee's regularity would guess, and guessing
    low understates your freedom rather than overstating it.
    """
    start, end = filters.window()
    currency = _currency_for(filters)

    spend = _scoped_transactions(filters, start, end).filter(amount_minor__lt=0)
    committed = abs(
        spend.filter(source=TransactionSource.RECURRING).aggregate(t=Sum("amount_minor"))["t"] or 0
    )
    total = abs(spend.aggregate(t=Sum("amount_minor"))["t"] or 0)
    discretionary = total - committed

    months = max(1, len(_month_range(start, end)))
    return ReportResult(
        slug="committed_vs_discretionary",
        title="Committed vs discretionary",
        currency=currency,
        start=start,
        end=end,
        totals={
            "total_minor": total,
            "committed_minor": committed,
            "discretionary_minor": discretionary,
            "committed_share": round(committed / total * 100, 1) if total else 0.0,
            "committed_monthly_minor": committed // months,
            "discretionary_monthly_minor": discretionary // months,
        },
        # A two-slice donut of zeroes would assert a shape to spending that
        # hasn't happened; an absence reports as empty instead.
        rows=(
            [
                {"label": "Committed", "amount_minor": committed},
                {"label": "Discretionary", "amount_minor": discretionary},
            ]
            if total
            else []
        ),
    )


def income_stability_report(filters: ReportFilters) -> ReportResult:
    """How predictable the money coming in actually is.

    Averages hide volatility, and volatility is what decides how large a buffer
    someone needs. Reporting the worst month alongside the average is the
    useful part: planning against a mean you only hit half the time is how
    people with irregular income get caught out.
    """
    start, end = filters.window()
    currency = _currency_for(filters)

    monthly = _monthly_totals(filters, start, end)
    months = _month_range(start, end)
    series = [
        {"month": month, "income_minor": monthly.get(month, {}).get("inflow_minor", 0)} for month in months
    ]

    # Exclude months with no income at all: usually a window that opens before
    # the account did, and a leading zero would fake a collapse.
    earning = [p["income_minor"] for p in series if p["income_minor"] > 0]
    if not earning:
        return ReportResult(
            slug="income_stability",
            title="Income stability",
            currency=currency,
            start=start,
            end=end,
            totals={"average_minor": 0, "lowest_minor": 0, "highest_minor": 0, "variation": 0.0},
            # A flat line of zero-income months reads as "your income
            # collapsed", which is a claim. No income recorded is an absence.
            series=[],
        )

    average = sum(earning) // len(earning)
    lowest, highest = min(earning), max(earning)
    spread = sum(abs(value - average) for value in earning) / len(earning) / average if average else 0

    return ReportResult(
        slug="income_stability",
        title="Income stability",
        currency=currency,
        start=start,
        end=end,
        totals={
            "average_minor": average,
            "lowest_minor": lowest,
            "highest_minor": highest,
            "months_counted": len(earning),
            # Mean absolute deviation as a share of the mean. Plainer than a
            # standard deviation and less distorted by one outlier month.
            "variation": round(spread * 100, 1),
            "shortfall_minor": average - lowest,
        },
        series=series,
    )


REPORTS: dict[str, Callable[[ReportFilters], ReportResult]] = {
    "net_worth": net_worth_report,
    "savings_rate": savings_rate_report,
    "cash_flow": cash_flow_report,
    "income_sources": income_sources_report,
    "expense_trends": expense_trends_report,
    "merchant_analytics": merchant_analytics_report,
    "category_analytics": category_analytics_report,
    "lifestyle_inflation": lifestyle_inflation_report,
    "monthly_comparison": monthly_comparison_report,
    "year_over_year": year_over_year_report,
    "income_vs_spending": income_vs_spending_report,
    "largest_purchases": largest_purchases_report,
    "subscription_costs": subscription_costs_report,
    "financial_health": financial_health_report,
    "category_movers": category_movers_report,
    "spending_by_weekday": spending_by_weekday_report,
    "committed_vs_discretionary": committed_vs_discretionary_report,
    "income_stability": income_stability_report,
}

#: Presentation hints, so the frontend can render an unfamiliar report without
#: a bespoke component. A report added later appears in the UI by registering
#: here rather than by shipping a new page.
REPORT_META: dict[str, dict] = {
    "net_worth": {"title": "Net worth", "chart": "area", "group": "position"},
    "savings_rate": {"title": "Savings rate", "chart": "line", "group": "position"},
    "financial_health": {"title": "Financial health", "chart": "score", "group": "position"},
    "cash_flow": {"title": "Cash flow", "chart": "bar", "group": "flow"},
    "income_vs_spending": {"title": "Income vs spending", "chart": "composed", "group": "flow"},
    "income_sources": {"title": "Income sources", "chart": "donut", "group": "flow"},
    "expense_trends": {"title": "Expense trends", "chart": "line", "group": "spending"},
    "category_analytics": {"title": "Categories", "chart": "donut", "group": "spending"},
    "merchant_analytics": {"title": "Merchants", "chart": "table", "group": "spending"},
    "largest_purchases": {"title": "Largest purchases", "chart": "table", "group": "spending"},
    "subscription_costs": {"title": "Subscriptions", "chart": "table", "group": "spending"},
    "monthly_comparison": {"title": "This month vs last", "chart": "table", "group": "compare"},
    "year_over_year": {"title": "Year over year", "chart": "bar", "group": "compare"},
    "lifestyle_inflation": {"title": "Lifestyle inflation", "chart": "composed", "group": "compare"},
    "income_stability": {"title": "Income stability", "chart": "line", "group": "position"},
    "spending_by_weekday": {"title": "Spending by day of week", "chart": "bar", "group": "spending"},
    "committed_vs_discretionary": {
        "title": "Committed vs discretionary",
        "chart": "donut",
        "group": "spending",
    },
    "category_movers": {"title": "What changed", "chart": "table", "group": "compare"},
}


def run_report(slug: str, filters: ReportFilters | None = None) -> ReportResult:
    """Run one report by slug, through the cache."""
    from .cache import cached_report

    if slug not in REPORTS:
        raise ValueError(f"Unknown report {slug!r}.")
    filters = filters or ReportFilters()

    return cached_report(
        slug=slug,
        filters_part=filters.cache_key_part(),
        compute=lambda: REPORTS[slug](filters),
    )
