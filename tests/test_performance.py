"""Performance characterisation.

Nothing in this system had a measured performance property. That is a different
gap from "it might be slow": without a number, a change that makes the
transaction list ten times more expensive is indistinguishable from one that
does not, and the first person to notice is a customer with four years of
history.

These are not load tests — there is no concurrency and no sustained traffic, so
they say nothing about throughput under real load. They are **characterisation
tests**: they build a realistically large workspace and assert two things that
can be asserted honestly in a test process.

**Query count** is the primary assertion, because it is deterministic. Wall time
on a shared CI runner is not; a threshold tight enough to catch a real
regression would flake, and a threshold loose enough not to flake would catch
nothing. Query count catches the regression that actually happens — an N+1
introduced by adding a field to a serializer — and catches it exactly.

**Scaling behaviour** is the secondary assertion: the same endpoint is measured
at two data sizes and the query count must not grow with the row count. That is
the property that distinguishes a slow endpoint from an unscalable one, and it
holds regardless of how fast the machine is.

Marked `slow` so the default suite stays fast:

    pytest -m slow          # just these
    pytest -m "not slow"    # everyone else
"""

from __future__ import annotations

import time

import pytest
from django.db import transaction as db_transaction
from django.utils import timezone

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory

pytestmark = [pytest.mark.django_db, pytest.mark.slow]

#: Big enough that an N+1 is unmistakable, small enough that the fixture builds
#: in a couple of seconds. The point is the *shape* of the cost curve.
SMALL, LARGE = 25, 250


def _workspace(transaction_count: int):
    """A workspace with a realistic amount of history."""
    membership = MembershipFactory()
    client = _bearer_client(membership.user, tenant_id=membership.tenant_id)

    account = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Current", "account_type": "checking", "currency": "USD"},
        format="json",
    ).data
    category = client.post(
        "/api/v1/finance/categories/",
        {"name": "Living", "kind": "expense", "currency": "USD"},
        format="json",
    ).data

    # Built through the service layer rather than bulk_create so the ledger,
    # balances and search vectors are all populated the way production is —
    # a fixture that skips them would measure a system nobody runs.
    from apps.finance import services as finance
    from apps.finance.models import Category, FinancialAccount

    with db_transaction.atomic():
        bind_db_tenant(membership.tenant_id)
        with use_tenant(membership.tenant_id, actor_id=membership.user_id):
            acct = FinancialAccount.objects.get(id=account["id"])
            cat = Category.objects.get(id=category["id"])
            for n in range(transaction_count):
                finance.record_expense(
                    financial_account=acct,
                    category=cat,
                    amount_minor=100 + n,
                    occurred_at=timezone.now() - timezone.timedelta(days=n % 365),
                    memo=f"Purchase {n}",
                )
    return membership, client, account, category


def _count_queries(fn):
    """Queries issued by `fn`, plus its wall time (reported, never asserted)."""
    from django.db import connection, reset_queries
    from django.test.utils import CaptureQueriesContext

    started = time.perf_counter()
    with CaptureQueriesContext(connection) as captured:
        result = fn()
    elapsed_ms = (time.perf_counter() - started) * 1000
    # Read the count *before* resetting: CaptureQueriesContext.__len__ slices
    # `connection.queries`, so clearing the log first makes every measurement
    # zero — and every assertion below pass while checking nothing.
    count = len(captured)
    reset_queries()
    return count, elapsed_ms, result


# ==================================================== does cost track rows?
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/finance/transactions/",
        "/api/v1/finance/accounts/",
        "/api/v1/analytics/reports/",
    ],
)
def test_list_query_count_does_not_grow_with_row_count(path):
    """The property that separates slow from unscalable.

    A page that costs 8 queries at 25 rows and 8 at 250 is fine however slow it
    is today. One that costs 30 then 255 will fall over in production and
    nowhere else.
    """
    _, small_client, _, _ = _workspace(SMALL)
    _, large_client, _, _ = _workspace(LARGE)

    small_queries, small_ms, _ = _count_queries(lambda: small_client.get(path))
    large_queries, large_ms, _ = _count_queries(lambda: large_client.get(path))

    print(f"\n  {path}: {SMALL} rows -> {small_queries}q/{small_ms:.0f}ms | "
          f"{LARGE} rows -> {large_queries}q/{large_ms:.0f}ms")

    # A couple of queries of slack for pagination counts and permission lookups
    # that legitimately vary; anything more is scaling with the data.
    assert large_queries <= small_queries + 2, (
        f"{path} issued {large_queries} queries at {LARGE} rows vs "
        f"{small_queries} at {SMALL} — the cost is tracking the row count."
    )


def test_the_dashboard_cost_does_not_grow_with_history():
    """The first screen after login, and the one users hit most."""
    _, small_client, _, _ = _workspace(SMALL)
    _, large_client, _, _ = _workspace(LARGE)

    small_queries, small_ms, small_response = _count_queries(
        lambda: small_client.get("/api/v1/intelligence/health-score/")
    )
    large_queries, large_ms, large_response = _count_queries(
        lambda: large_client.get("/api/v1/intelligence/health-score/")
    )
    assert small_response.status_code == 200
    assert large_response.status_code == 200

    print(f"\n  health-score: {SMALL} rows -> {small_queries}q/{small_ms:.0f}ms | "
          f"{LARGE} rows -> {large_queries}q/{large_ms:.0f}ms")
    assert large_queries <= small_queries + 2


def test_a_report_over_a_year_of_history_is_bounded():
    """Analytics aggregate in the database, so the query count must be flat
    even though the data volume is not."""
    _, client, _, _ = _workspace(LARGE)
    queries, elapsed_ms, response = _count_queries(
        lambda: client.get("/api/v1/analytics/reports/spending_by_weekday/")
    )
    assert response.status_code == 200
    print(f"\n  spending_by_weekday over {LARGE} rows: {queries}q/{elapsed_ms:.0f}ms")
    assert queries < 25, f"a single report issued {queries} queries"


# ================================================== platform console scaling
def test_the_tenant_directory_does_not_scale_with_tenant_count():
    """The console's busiest screen. It already has a fixed-query-count test at
    one size; this checks the curve rather than the point."""
    from apps.platform_admin.rbac import PlatformRole
    from tests.test_platform_admin_rbac import client_for, make_staff

    for _ in range(3):
        MembershipFactory()
    staff = make_staff(PlatformRole.OWNER)
    api = client_for(staff)
    few_queries, few_ms, _ = _count_queries(lambda: api.get("/api/v1/platform/tenants/"))

    for _ in range(20):
        MembershipFactory()
    many_queries, many_ms, response = _count_queries(lambda: api.get("/api/v1/platform/tenants/"))

    assert response.status_code == 200
    print(f"\n  platform tenants: 3 -> {few_queries}q/{few_ms:.0f}ms | "
          f"23 -> {many_queries}q/{many_ms:.0f}ms")
    assert many_queries <= few_queries + 2


# ============================================================ bulk ingestion
def test_csv_import_cost_is_linear_not_quadratic():
    """Import is the one operation users run on thousands of rows at once.

    Linear is expected — each row is a real ledger posting. Quadratic is the
    failure mode: a per-row query that scans everything imported so far, which
    is invisible at 10 rows and fatal at 5,000.
    """
    membership, client, account, category = _workspace(0)

    def csv_of(n, offset=0):
        rows = "\n".join(
            f"2026-03-{(i % 28) + 1:02d},MERCHANT {i},-{10 + i}.00,batch-{offset + i}"
            for i in range(n)
        )
        return f"date,description,amount,external_id\n{rows}"

    small_queries, small_ms, small = _count_queries(
        lambda: client.post(
            "/api/v1/finance/transactions/import/",
            {"account_id": account["id"], "content": csv_of(20),
             "default_category_id": category["id"]},
            format="json",
        )
    )
    large_queries, large_ms, large = _count_queries(
        lambda: client.post(
            "/api/v1/finance/transactions/import/",
            {"account_id": account["id"], "content": csv_of(80, offset=1000),
             "default_category_id": category["id"]},
            format="json",
        )
    )
    assert small.data["imported"] == 20
    assert large.data["imported"] == 80

    per_row_small = small_queries / 20
    per_row_large = large_queries / 80
    print(f"\n  import: 20 rows -> {small_queries}q ({per_row_small:.1f}/row, {small_ms:.0f}ms) | "
          f"80 rows -> {large_queries}q ({per_row_large:.1f}/row, {large_ms:.0f}ms)")

    # Per-row cost must stay flat. A quadratic path shows up here as the
    # per-row figure climbing with batch size.
    assert per_row_large <= per_row_small * 1.5, (
        f"per-row query cost grew from {per_row_small:.1f} to {per_row_large:.1f} — "
        "the importer is doing work proportional to what it has already imported."
    )

    # The measured constant, pinned so it cannot drift upward unnoticed.
    #
    # ~15 queries per row is *linear*, which is the property that matters — but
    # it is not cheap. Each imported row is a real ledger posting: a journal
    # entry, its lines, an account lock, a balance update and a dedupe check.
    # A year of statements (~2,000 rows) is therefore ~30,000 queries, and the
    # measured 80-row batch already takes a second.
    #
    # That is acceptable for the CSV path people run occasionally and would not
    # be for a nightly bank-feed sync across every tenant. Batching the postings
    # is the fix when aggregation arrives; until then this assertion makes the
    # cost visible instead of surprising.
    assert per_row_large < 20, (
        f"import now costs {per_row_large:.1f} queries per row (was ~15). "
        "Something added per-row work to the ingestion path."
    )


# ============================================================== reconciliation
def test_reconciling_a_large_batch_is_a_bounded_number_of_queries():
    """A statement can carry hundreds of lines; the endpoint takes them in one
    request, so it must not issue a query per row."""
    from apps.finance.models import Transaction

    membership, client, account, _ = _workspace(LARGE)
    with db_transaction.atomic():
        bind_db_tenant(membership.tenant_id)
        with use_tenant(membership.tenant_id, actor_id=membership.user_id):
            ids = [str(t.id) for t in Transaction.objects.all()[:200]]

    queries, elapsed_ms, response = _count_queries(
        lambda: client.post(
            "/api/v1/finance/transactions/reconcile/",
            {"transaction_ids": ids},
            format="json",
        )
    )
    assert response.status_code == 200
    assert response.data["updated"] == 200
    print(f"\n  reconcile 200 rows: {queries}q/{elapsed_ms:.0f}ms")
    assert queries < 30, f"reconciling 200 rows issued {queries} queries"
