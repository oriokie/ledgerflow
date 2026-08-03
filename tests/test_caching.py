"""Tests for tenant-scoped analytics caching and invalidation.

The correctness risk with caching financial analytics is staleness: after a
write, the cached health score / recommendations must not be served. These
prove the version-bump invalidation works and that caches are tenant-isolated.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from apps.common import cache as cache_util
from apps.common.tenant_context import use_tenant
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def test_cached_analytics_returns_cached_value_then_invalidates():
    tenant = uuid.uuid4()
    calls = {"n": 0}

    @cache_util.cached_analytics("t_metric", ttl=300)
    def compute():
        calls["n"] += 1
        return {"value": calls["n"]}

    with use_tenant(tenant):
        first = compute()
        second = compute()  # served from cache — compute() not re-run
        assert first == second == {"value": 1}
        assert calls["n"] == 1

        cache_util.invalidate_tenant(tenant)  # version bump orphans the key
        third = compute()
        assert third == {"value": 2}
        assert calls["n"] == 2


def test_cache_is_tenant_isolated():
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    seen = []

    @cache_util.cached_analytics("iso_metric", ttl=300)
    def compute():
        seen.append(1)
        return {"n": len(seen)}

    with use_tenant(tenant_a):
        a = compute()
    with use_tenant(tenant_b):
        b = compute()  # different tenant -> different key -> recomputed
    assert a == {"n": 1}
    assert b == {"n": 2}  # not served tenant A's cached value


def test_transaction_write_invalidates_analytics_cache(django_capture_on_commit_callbacks):
    """A posted transaction must bump the tenant cache version so a cached
    health score isn't served stale. on_commit fires the invalidation, so we
    capture and run those callbacks explicitly in the test transaction."""
    from apps.finance import services as fs
    from apps.finance.models import AccountType, CategoryKind

    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        v_before = cache_util.current_version(str(tenant))
        with django_capture_on_commit_callbacks(execute=True):
            checking = fs.create_financial_account(
                name="C", account_type=AccountType.CHECKING, currency="USD"
            )
            cat = fs.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
            fs.record_expense(
                financial_account=checking,
                category=cat,
                amount_minor=500,
                occurred_at=datetime.now(UTC),
            )
        v_after = cache_util.current_version(str(tenant))
        assert v_after > v_before
