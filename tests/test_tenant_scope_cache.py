"""The per-request memoisation behind the household boundary checks.

This cache answers "who is acting", "how many members are there" and "which
accounts may they see" — the questions every guarded query asks. Memoising them
took a transaction listing in a two-person workspace from 19 queries to 13.

The reason it needs its own tests is the failure mode. A cache that outlived
its tenant binding would serve one household's visibility answers to another,
which is precisely the leak the whole boundary exists to prevent. Speed is the
motive; isolation is the requirement.
"""

from __future__ import annotations

import pytest

from apps.common.tenant_context import (
    cached_per_tenant_scope,
    invalidate_tenant_scope_cache,
    use_tenant,
)
from apps.household.visibility import is_single_member_workspace
from tests.factories import MembershipFactory, TenantFactory
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


class TestLifecycle:
    def test_a_value_is_produced_once_inside_one_scope(self):
        calls = []
        with use_tenant(TenantFactory().id):
            for _ in range(3):
                cached_per_tenant_scope("k", lambda: calls.append(1) or "v")
        assert len(calls) == 1

    def test_the_cache_does_not_survive_the_scope(self):
        """The property that makes this safe. A cache outliving its tenant
        would hand one household's answers to another."""
        calls = []
        produce = lambda: calls.append(1) or "v"  # noqa: E731
        tenant = TenantFactory()
        with use_tenant(tenant.id):
            cached_per_tenant_scope("k", produce)
        with use_tenant(tenant.id):
            cached_per_tenant_scope("k", produce)
        assert len(calls) == 2, "each binding starts with an empty cache"

    def test_two_tenants_never_share_an_answer(self):
        first, second = TenantFactory(), TenantFactory()
        with use_tenant(first.id):
            cached_per_tenant_scope("k", lambda: "first's answer")
        with use_tenant(second.id):
            assert cached_per_tenant_scope("k", lambda: "second's answer") == "second's answer"

    def test_it_falls_through_when_nothing_is_bound(self):
        """A management command calling a selector directly must behave the
        same, just without the saving."""
        calls = []
        for _ in range(2):
            cached_per_tenant_scope("k", lambda: calls.append(1) or "v")
        assert len(calls) == 2


class TestInvalidation:
    def test_a_named_key_can_be_dropped(self):
        calls = []
        produce = lambda: calls.append(1) or "v"  # noqa: E731
        with use_tenant(TenantFactory().id):
            cached_per_tenant_scope("k", produce)
            invalidate_tenant_scope_cache("k")
            cached_per_tenant_scope("k", produce)
        assert len(calls) == 2

    def test_dropping_one_key_leaves_the_others(self):
        calls = []
        with use_tenant(TenantFactory().id):
            cached_per_tenant_scope("a", lambda: calls.append("a") or 1)
            cached_per_tenant_scope("b", lambda: calls.append("b") or 2)
            invalidate_tenant_scope_cache("a")
            cached_per_tenant_scope("a", lambda: calls.append("a") or 1)
            cached_per_tenant_scope("b", lambda: calls.append("b") or 2)
        assert calls == ["a", "b", "a"]


class TestRealCallers:
    def test_membership_count_is_asked_once_per_request(self, django_assert_num_queries):
        """It is consulted by visible_account_ids, hidden_transaction_ids and
        redaction_levels — three times per listing before this."""
        tenant = TenantFactory()
        MembershipFactory(tenant=tenant)
        MembershipFactory(tenant=tenant)
        with tenant_scope(tenant.id), django_assert_num_queries(1):
            for _ in range(5):
                is_single_member_workspace()

    def test_the_answer_is_still_correct_per_workspace(self):
        solo, couple = TenantFactory(), TenantFactory()
        MembershipFactory(tenant=solo)
        MembershipFactory(tenant=couple)
        MembershipFactory(tenant=couple)

        with tenant_scope(solo.id):
            assert is_single_member_workspace() is True
        with tenant_scope(couple.id):
            assert is_single_member_workspace() is False
