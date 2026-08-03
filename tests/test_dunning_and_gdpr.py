"""Journeys: past-due dunning recovery, and GDPR data export + workspace closure."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.billing import services as billing
from apps.billing.models import BillingInterval, Plan, PlanTier, SubscriptionStatus
from apps.tenancy import selectors, services as tenancy
from apps.tenancy.models import Role

pytestmark = pytest.mark.django_db


def _client(user, tenant_id=None):
    c = APIClient()
    headers = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}
    if tenant_id:
        headers["HTTP_X_TENANT_ID"] = str(tenant_id)
    c.credentials(**headers)
    return c


# ------------------------------------------------------------------ dunning

def test_retry_reactivates_a_past_due_free_subscription(tenant_context):
    membership, client = tenant_context
    free = Plan.objects.create(
        tier=PlanTier.FREE, name="Free", price_minor=0, currency="USD",
        interval=BillingInterval.MONTHLY, max_accounts=3, max_members=1,
    )
    sub = billing.subscribe(tenant_id=membership.tenant_id, plan=free)
    sub.status = SubscriptionStatus.PAST_DUE
    sub.save(update_fields=["status"])

    res = client.post("/api/v1/billing/subscription/retry/")
    assert res.status_code == 200, res.data
    assert res.data["status"] == "active"


def test_retry_without_subscription_is_rejected(tenant_context):
    _, client = tenant_context
    res = client.post("/api/v1/billing/subscription/retry/")
    assert res.status_code == 422


def test_failed_payment_webhook_marks_subscription_past_due(tenant_context):
    """A failed charge event flips an active subscription to past_due."""
    from apps.billing.models import Payment, PaymentStatus

    membership, _ = tenant_context
    free = Plan.objects.create(
        tier=PlanTier.FREE, name="Free", price_minor=0, currency="USD",
        interval=BillingInterval.MONTHLY, max_accounts=3, max_members=1,
    )
    sub = billing.subscribe(tenant_id=membership.tenant_id, plan=free)
    payment = Payment.objects.create(
        tenant_id=membership.tenant_id, subscription=sub, amount_minor=900, currency="USD",
        status=PaymentStatus.PENDING, provider="stripe", provider_ref="pi_test_fail",
    )
    # Simulate the provider-normalized failure the webhook path applies.
    from types import SimpleNamespace

    billing._apply_webhook(SimpleNamespace(normalized_type="payment.failed", provider_ref="pi_test_fail"))
    sub.refresh_from_db()
    assert sub.status == SubscriptionStatus.PAST_DUE
    payment.refresh_from_db()
    assert payment.status == PaymentStatus.FAILED


# ------------------------------------------------------------------ gdpr

def test_export_returns_workspace_data_for_owner(tenant_context):
    membership, client = tenant_context
    res = client.get(f"/api/v1/tenancy/workspaces/{membership.tenant_id}/export/")
    assert res.status_code == 200
    for key in ("workspace", "accounts", "categories", "transactions", "budgets", "goals", "bills"):
        assert key in res.data
    assert res.data["workspace"]["id"] == str(membership.tenant_id)


def test_export_denied_for_non_owner(tenant_context, user):
    membership, _ = tenant_context
    tenancy.add_member(tenant=membership.tenant, user=user, role=Role.VIEWER)
    viewer_client = _client(user, membership.tenant_id)
    res = viewer_client.get(f"/api/v1/tenancy/workspaces/{membership.tenant_id}/export/")
    assert res.status_code == 403


def test_close_workspace_removes_it_from_the_owner_list(tenant_context):
    membership, client = tenant_context
    res = client.delete(f"/api/v1/tenancy/workspaces/{membership.tenant_id}/")
    assert res.status_code == 204
    # Gone from the switcher list, and marked inactive.
    remaining = selectors.memberships_for_user(membership.user)
    assert all(m.tenant_id != membership.tenant_id for m in remaining)
    membership.tenant.refresh_from_db()
    assert membership.tenant.is_active is False


def test_close_denied_for_non_owner(tenant_context, user):
    membership, _ = tenant_context
    tenancy.add_member(tenant=membership.tenant, user=user, role=Role.VIEWER)
    viewer_client = _client(user, membership.tenant_id)
    res = viewer_client.delete(f"/api/v1/tenancy/workspaces/{membership.tenant_id}/")
    assert res.status_code == 403
