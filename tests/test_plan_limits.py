"""Subscription lifecycle journey: an active plan's account/member limits are
enforced, upgrading raises them, and tenants with no subscription are unmetered."""

from __future__ import annotations

import contextlib

import pytest
from django.db import transaction

from apps.billing import services as billing_services
from apps.billing.entitlements import PlanLimitExceeded, resolve_entitlements
from apps.billing.models import BillingInterval, Plan, PlanTier
from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from apps.finance import services as finance_services
from apps.tenancy import services as tenancy_services
from apps.tenancy.models import Role

pytestmark = pytest.mark.django_db


def _plan(*, tier, accounts, members, price=0):
    return Plan.objects.create(
        tier=tier,
        name=str(tier),
        price_minor=price,
        currency="USD",
        interval=BillingInterval.MONTHLY,
        max_accounts=accounts,
        max_members=members,
    )


def _make_account(name):
    finance_services.create_financial_account(name=name, account_type="checking", currency="USD")


def test_no_subscription_is_unmetered(tenant_context, django_assert_num_queries=None):
    membership, _ = tenant_context
    ent = resolve_entitlements(tenant_id=membership.tenant_id)
    assert ent.metered is False
    assert ent.max_accounts is None
    # Can create well past any plan cap.
    with use_tenant(membership.tenant_id, membership.user_id), _in_tx(membership.tenant_id):
        for i in range(5):
            _make_account(f"Acct {i}")


def test_active_plan_caps_accounts_then_upgrade_lifts_it(tenant_context):
    membership, _ = tenant_context
    tenant_id = membership.tenant_id
    free = _plan(tier=PlanTier.FREE, accounts=2, members=1)
    billing_services.subscribe(tenant_id=tenant_id, plan=free)

    with use_tenant(tenant_id, membership.user_id), _in_tx(tenant_id):
        _make_account("One")
        _make_account("Two")
        with pytest.raises(PlanLimitExceeded):
            _make_account("Three")  # over the cap of 2

    # Upgrade to a roomier plan; the third account now fits.
    plus = _plan(tier=PlanTier.PLUS, accounts=25, members=5)  # price 0: limits are the point here
    billing_services.subscribe(tenant_id=tenant_id, plan=plus)
    with use_tenant(tenant_id, membership.user_id), _in_tx(tenant_id):
        _make_account("Three")


def test_active_plan_caps_members(tenant_context, user):
    membership, _ = tenant_context
    tenant_id = membership.tenant_id
    solo = _plan(tier=PlanTier.FREE, accounts=3, members=1)  # owner only
    billing_services.subscribe(tenant_id=tenant_id, plan=solo)

    with pytest.raises(PlanLimitExceeded):
        tenancy_services.add_member(tenant=membership.tenant, user=user, role=Role.MEMBER)


# --- helpers -------------------------------------------------------------


@contextlib.contextmanager
def _in_tx(tenant_id):
    with transaction.atomic():
        bind_db_tenant(tenant_id)
        yield


def test_account_creation_over_cap_returns_402(tenant_context):
    """The HTTP surface returns 402 with an upgrade-oriented message."""
    membership, client = tenant_context
    billing_services.subscribe(
        tenant_id=membership.tenant_id, plan=_plan(tier=PlanTier.FREE, accounts=1, members=1)
    )

    first = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD"},
        format="json",
    )
    assert first.status_code == 201, first.data

    second = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Savings", "account_type": "savings", "currency": "USD"},
        format="json",
    )
    assert second.status_code == 402, second.data
    assert "upgrade" in str(second.data).lower()


def test_ai_insights_gated_by_plan(tenant_context):
    """Health/recommendations require a plan with ai_insights; analytics don't."""
    membership, client = tenant_context
    tid = membership.tenant_id

    # Metered plan WITHOUT ai_insights → AI endpoints are 402, analytics still 200.
    no_ai = Plan.objects.create(
        tier=PlanTier.FREE,
        name="Free",
        price_minor=0,
        currency="USD",
        interval=BillingInterval.MONTHLY,
        max_accounts=3,
        max_members=1,
        ai_insights=False,
    )
    billing_services.subscribe(tenant_id=tid, plan=no_ai)

    assert client.get("/api/v1/intelligence/health-score/").status_code == 402
    assert client.get("/api/v1/intelligence/recommendations/").status_code == 402
    # Deterministic analytics remain available.
    assert client.get("/api/v1/intelligence/net-worth-history/").status_code == 200

    # Upgrade to a plan WITH ai_insights → AI endpoints unlock.
    with_ai = Plan.objects.create(
        tier=PlanTier.PLUS,
        name="Plus",
        price_minor=0,
        currency="USD",
        interval=BillingInterval.MONTHLY,
        max_accounts=25,
        max_members=5,
        ai_insights=True,
    )
    billing_services.subscribe(tenant_id=tid, plan=with_ai)
    assert client.get("/api/v1/intelligence/health-score/").status_code == 200
