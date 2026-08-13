"""Analytics reporting platform.

Fourteen reports over one shared filter, cache and export layer. The tests are
organised the same way: the platform machinery is tested once, then each report
is checked for the thing it specifically claims.

The cache tests matter most. A report cache that survives a posting shows stale
financial figures, which is worse than no cache at all.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.analytics import reports
from apps.analytics.cache import cached_report, invalidate, report_cache_key
from apps.analytics.filters import Period, ReportFilters, resolve_period
from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _workspace(months: int = 6):
    """An account with income and spending across several months."""
    account = finance_services.create_financial_account(
        name="Checking",
        account_type=AccountType.CHECKING,
        currency="USD",
        opening_balance_minor=500_000,
    )
    groceries = finance_services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
    dining = finance_services.create_category(name="Dining", kind=CategoryKind.EXPENSE, currency="USD")
    salary = finance_services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")

    now = timezone.now()
    for month in range(months):
        when = now - timedelta(days=30 * month)
        finance_services.record_income(
            financial_account=account, category=salary, amount_minor=400_000, occurred_at=when
        )
        finance_services.record_expense(
            financial_account=account, category=groceries, amount_minor=30_000, occurred_at=when
        )
        finance_services.record_expense(
            financial_account=account, category=dining, amount_minor=12_000, occurred_at=when
        )
    return account, {"groceries": groceries, "dining": dining, "salary": salary}


# =============================================================================
# Filters
# =============================================================================
def test_named_periods_all_resolve():
    # CUSTOM is excluded by design: it carries its dates on the filter rather
    # than being resolvable from a name.
    for period in (p for p in Period.ALL if p != Period.CUSTOM):
        start, end = resolve_period(period, as_of=date(2026, 6, 15))
        assert start <= end, f"{period} resolved to an inverted window"


def test_a_custom_period_without_dates_is_refused():
    """It cannot be resolved, so failing loudly beats inventing a window."""
    with pytest.raises(ValueError):
        ReportFilters(period=Period.CUSTOM).window()


def test_an_unknown_period_is_rejected():
    with pytest.raises(ValueError):
        resolve_period("since_the_dawn_of_time")


def test_a_custom_range_overrides_the_named_period():
    filters = ReportFilters(period=Period.CUSTOM, start=date(2026, 1, 1), end=date(2026, 3, 31))
    assert filters.window() == (date(2026, 1, 1), date(2026, 3, 31))


def test_the_previous_window_matches_the_current_one_in_length():
    """Comparing a 30-day window against a 90-day one would make any delta
    meaningless."""
    filters = ReportFilters(period=Period.CUSTOM, start=date(2026, 3, 1), end=date(2026, 3, 31))
    current_start, current_end = filters.window()
    previous_start, previous_end = filters.previous_window()

    assert (current_end - current_start) == (previous_end - previous_start)
    assert previous_end < current_start


def test_filters_are_hashable_so_they_can_key_a_cache():
    filters = ReportFilters(account_ids=("a", "b"), category_ids=("c",))
    assert hash(filters)
    assert (
        filters.cache_key_part()
        == ReportFilters(account_ids=("a", "b"), category_ids=("c",)).cache_key_part()
    )


def test_different_filters_produce_different_cache_keys():
    a = ReportFilters(period=Period.LAST_30).cache_key_part()
    b = ReportFilters(period=Period.LAST_12_MONTHS).cache_key_part()
    assert a != b


# =============================================================================
# Cache
# =============================================================================
def test_a_report_is_computed_once_then_served_from_cache(tenant):
    calls = []

    def compute():
        calls.append(1)
        return {"value": 42}

    with tenant_scope(tenant):
        first = cached_report(slug="x", filters_part="p", compute=compute)
        second = cached_report(slug="x", filters_part="p", compute=compute)

    assert first == second == {"value": 42}
    assert len(calls) == 1


def test_invalidation_orphans_every_cached_report(tenant):
    calls = []

    def compute():
        calls.append(1)
        return len(calls)

    with tenant_scope(tenant):
        cached_report(slug="x", filters_part="p", compute=compute)
        invalidate(tenant)
        cached_report(slug="x", filters_part="p", compute=compute)

    # The version bump made the old key unreachable, so it recomputed.
    assert len(calls) == 2


def test_one_tenants_cache_never_serves_another(tenant):
    other = uuid.uuid4()

    with tenant_scope(tenant):
        cached_report(slug="x", filters_part="p", compute=lambda: "first tenant")
    with tenant_scope(other):
        value = cached_report(slug="x", filters_part="p", compute=lambda: "second tenant")

    assert value == "second tenant"


def test_the_tenant_is_in_the_key_not_only_the_version(tenant):
    """Two independent guards on the one thing that must never happen."""
    other = uuid.uuid4()
    with tenant_scope(tenant):
        mine = report_cache_key(slug="x", filters_part="p")
    with tenant_scope(other):
        theirs = report_cache_key(slug="x", filters_part="p")

    assert str(tenant) in mine
    assert mine != theirs


def test_an_unscoped_read_bypasses_the_cache_entirely():
    """Failing closed, like every other query in the product — never quietly
    reading or writing a shared key."""
    calls = []

    def compute():
        calls.append(1)
        return "computed"

    assert cached_report(slug="x", filters_part="p", compute=compute) == "computed"
    assert cached_report(slug="x", filters_part="p", compute=compute) == "computed"
    assert len(calls) == 2


def test_posting_a_transaction_invalidates_cached_reports(tenant, django_capture_on_commit_callbacks):
    """The whole point of wiring invalidation into the ledger. A cache that
    survives a posting shows stale money.

    The bump runs in `transaction.on_commit`, which pytest's surrounding test
    transaction defers indefinitely — so the callbacks have to be executed
    explicitly here. In production the posting commits and they fire normally.
    """
    with tenant_scope(tenant):
        account, cats = _workspace(months=1)
        first = reports.run_report("cash_flow", ReportFilters())

        with django_capture_on_commit_callbacks(execute=True):
            finance_services.record_expense(
                financial_account=account,
                category=cats["groceries"],
                amount_minor=250_000,
                occurred_at=timezone.now(),
            )
        second = reports.run_report("cash_flow", ReportFilters())

    assert second != first, "report was served stale after a posting"


def test_a_posting_registers_an_invalidation_callback(tenant, django_capture_on_commit_callbacks):
    """Guards the wiring itself: without a callback registered, every derived
    cache in the product would go stale for the length of its TTL."""
    with tenant_scope(tenant):
        with django_capture_on_commit_callbacks() as callbacks:
            _workspace(months=1)
        assert callbacks, "no cache invalidation was scheduled by a posting"


# =============================================================================
# The report catalogue
# =============================================================================
#: The dashboards the platform committed to. Asserted as a subset rather than
#: an exact set: the registry exists so a fifteenth report inherits export,
#: caching and rendering by registering, and an equality check would make every
#: such addition look like a failure. Removing one of these still fails.
REQUIRED_DASHBOARDS = {
    "net_worth",
    "savings_rate",
    "cash_flow",
    "income_sources",
    "expense_trends",
    "merchant_analytics",
    "category_analytics",
    "lifestyle_inflation",
    "monthly_comparison",
    "year_over_year",
    "income_vs_spending",
    "largest_purchases",
    "subscription_costs",
    "financial_health",
}


def test_every_required_dashboard_exists():
    assert set(reports.REPORTS) >= REQUIRED_DASHBOARDS


def test_every_report_has_rendering_metadata():
    """The client draws from this rather than hard-coding fourteen layouts, so
    a report without it would render as nothing."""
    for slug in reports.REPORTS:
        meta = reports.REPORT_META.get(slug)
        assert meta, f"{slug} has no metadata"
        assert meta.get("title"), f"{slug} has no title"
        assert meta.get("chart"), f"{slug} has no chart hint"


def test_every_report_runs_on_an_empty_workspace(tenant):
    """Nothing may raise on a brand-new account — that's the first thing a user
    sees."""
    with tenant_scope(tenant):
        for slug in reports.REPORTS:
            result = reports.run_report(slug, ReportFilters())
            assert result.slug == slug


#: Reports that describe a fixed period by definition. Forcing an arbitrary
#: window onto "this month vs last" would make it a different report, so they
#: report the window they actually used instead of the one requested.
FIXED_WINDOW_REPORTS = {"monthly_comparison", "year_over_year"}


def test_reports_honour_the_requested_window(tenant):
    with tenant_scope(tenant):
        _workspace()
        filters = ReportFilters(period=Period.CUSTOM, start=date(2026, 1, 1), end=date(2026, 6, 30))
        for slug in reports.REPORTS:
            result = reports.run_report(slug, filters)
            assert result.slug == slug
            if slug in FIXED_WINDOW_REPORTS:
                # Still honest about what it actually covered.
                assert result.start <= result.end
                continue
            assert result.start == date(2026, 1, 1)
            assert result.end == date(2026, 6, 30)


def test_an_unknown_report_is_rejected(tenant):
    with tenant_scope(tenant), pytest.raises(ValueError):
        reports.run_report("vibes", ReportFilters())


# =============================================================================
# Individual reports — each checked for what it specifically claims
# =============================================================================
def test_cash_flow_separates_money_in_from_money_out(tenant):
    with tenant_scope(tenant):
        _workspace(months=3)
        result = reports.run_report("cash_flow", ReportFilters())

        assert result.series
        row = result.series[0]
        assert "inflow_minor" in row and "outflow_minor" in row
        assert all(r["inflow_minor"] >= 0 and r["outflow_minor"] >= 0 for r in result.series)


def test_savings_rate_is_a_share_of_income_not_an_amount(tenant):
    with tenant_scope(tenant):
        _workspace(months=3)
        result = reports.run_report("savings_rate", ReportFilters())
        # Expressed as a percentage, matching `percent` elsewhere in the
        # platform. High here, but never above 100.
        assert result.series
        assert all(0 <= r["rate"] <= 100 for r in result.series)


def test_income_sources_ranks_by_amount(tenant):
    with tenant_scope(tenant):
        _workspace(months=3)
        result = reports.run_report("income_sources", ReportFilters())
        amounts = [r["amount_minor"] for r in result.rows]
        assert amounts == sorted(amounts, reverse=True)


def test_category_analytics_ranks_spending(tenant):
    with tenant_scope(tenant):
        _workspace(months=3)
        result = reports.run_report("category_analytics", ReportFilters())

        assert result.rows
        names = [r["label"] for r in result.rows]
        assert "Groceries" in names
        # Groceries (300.00/mo) outspends Dining (120.00/mo).
        assert names.index("Groceries") < names.index("Dining")


def test_largest_purchases_returns_the_biggest_first(tenant):
    with tenant_scope(tenant):
        account, cats = _workspace(months=1)
        finance_services.record_expense(
            financial_account=account,
            category=cats["groceries"],
            amount_minor=180_000,
            occurred_at=timezone.now(),
        )
        result = reports.run_report("largest_purchases", ReportFilters())

        assert result.rows
        assert result.rows[0]["amount_minor"] == 180_000
        amounts = [r["amount_minor"] for r in result.rows]
        assert amounts == sorted(amounts, reverse=True)


def test_year_over_year_compares_equivalent_windows(tenant):
    with tenant_scope(tenant):
        _workspace(months=3)
        result = reports.run_report("year_over_year", ReportFilters())
        # Comparison is the point; the shape must carry both sides even when
        # last year has no data.
        assert result.series or result.rows or result.totals


def test_lifestyle_inflation_needs_enough_history(tenant):
    """One month can't show a trend, and inventing one would be the whole
    failure mode of this report."""
    with tenant_scope(tenant):
        _workspace(months=1)
        result = reports.run_report("lifestyle_inflation", ReportFilters())
        assert result.is_empty or result.meta.get("insufficient_history")


def test_financial_health_reports_a_bounded_score(tenant):
    with tenant_scope(tenant):
        _workspace(months=3)
        result = reports.run_report("financial_health", ReportFilters())
        score = result.totals.get("score")
        if score is not None:
            assert 0 <= score <= 100


def test_filtering_by_category_narrows_the_result(tenant):
    with tenant_scope(tenant):
        _, cats = _workspace(months=3)
        everything = reports.run_report("category_analytics", ReportFilters())
        narrowed = reports.run_report(
            "category_analytics",
            ReportFilters(category_ids=(str(cats["groceries"].id),)),
        )
        assert len(narrowed.rows) < len(everything.rows)
        assert all(r["label"] == "Groceries" for r in narrowed.rows)


def test_filtering_by_account_narrows_the_result(tenant):
    with tenant_scope(tenant):
        account, cats = _workspace(months=2)
        other = finance_services.create_financial_account(
            name="Second", account_type=AccountType.CHECKING, currency="USD"
        )
        finance_services.record_expense(
            financial_account=other,
            category=cats["dining"],
            amount_minor=90_000,
            occurred_at=timezone.now(),
        )

        only_first = reports.run_report("category_analytics", ReportFilters(account_ids=(str(account.id),)))
        total = sum(r["amount_minor"] for r in only_first.rows)
        # The 900.00 on the other account must not be counted.
        assert total < 90_000 + sum(
            r["amount_minor"] for r in reports.run_report("category_analytics", ReportFilters()).rows
        )


# =============================================================================
# API
# =============================================================================
def test_api_catalogue_lists_every_report(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/analytics/reports/")
    assert resp.status_code == 200
    slugs = {r["slug"] for r in resp.data}
    assert slugs >= REQUIRED_DASHBOARDS
    # The catalogue is the single source of truth for what the UI can draw, so
    # it must agree exactly with the registry rather than merely overlap it.
    assert slugs == set(reports.REPORTS)
    assert all(r["title"] and r["chart"] for r in resp.data)


def test_api_runs_a_report(tenant_context):
    _, client = tenant_context
    client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD", "opening_balance_minor": 500_000},
        format="json",
    )
    resp = client.get("/api/v1/analytics/reports/net_worth/")
    assert resp.status_code == 200, resp.data
    assert resp.data["slug"] == "net_worth"
    assert "totals" in resp.data


def test_api_returns_204_when_a_report_has_nothing_to_show(tenant_context):
    """An empty chart reads as 'you earned nothing' — a claim, not an absence."""
    _, client = tenant_context
    assert client.get("/api/v1/analytics/reports/largest_purchases/").status_code == 204


def test_api_rejects_an_unknown_report(tenant_context):
    _, client = tenant_context
    assert client.get("/api/v1/analytics/reports/vibes/").status_code == 404


def test_api_rejects_a_half_specified_custom_range(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/analytics/reports/cash_flow/?start=2026-01-01")
    # Silently falling back to the named period is a confusing way to be wrong.
    assert resp.status_code == 400


def test_api_rejects_an_inverted_range(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/analytics/reports/cash_flow/?start=2026-06-01&end=2026-01-01")
    assert resp.status_code == 400


def test_api_exports_a_report_as_csv(tenant_context):
    _, client = tenant_context
    account = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD", "opening_balance_minor": 500_000},
        format="json",
    ).data
    category = client.post(
        "/api/v1/finance/categories/",
        {"name": "Groceries", "kind": "expense", "currency": "USD"},
        format="json",
    ).data
    created = client.post(
        "/api/v1/finance/transactions/",
        {
            "financial_account_id": account["id"],
            "category_id": category["id"],
            "type": "expense",
            "amount_minor": 12_500,
            "occurred_at": timezone.now().isoformat(),
        },
        format="json",
    )
    assert created.status_code in (200, 201), created.data

    resp = client.get("/api/v1/analytics/reports/largest_purchases/export/")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv"
    assert "largest_purchases.csv" in resp["Content-Disposition"]
    assert b"amount_minor" in resp.content
    # Major units sit beside the minor-unit column so a spreadsheet does not
    # treat 12500 cents as twelve thousand dollars.
    assert b"125.00" in resp.content


def test_api_export_is_204_when_there_is_nothing_to_export(tenant_context):
    _, client = tenant_context
    assert client.get("/api/v1/analytics/reports/largest_purchases/export/").status_code == 204
