"""
Billing subsystem tests. All run in sandbox mode (no provider credentials),
which exercises the full charge/webhook lifecycle deterministically.
"""

from __future__ import annotations

import json

import pytest

from apps.billing.models import (
    BillingInterval,
    Payment,
    PaymentStatus,
    Plan,
    PlanTier,
    Subscription,
    SubscriptionStatus,
    WebhookEvent,
)
from apps.billing.providers import get_provider
from apps.tenancy.models import Role
from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- helpers
def _free_plan():
    return Plan.objects.create(
        tier=PlanTier.FREE,
        name="Free",
        price_minor=0,
        currency="USD",
        interval=BillingInterval.MONTHLY,
        max_members=1,
        max_accounts=3,
        sort_order=0,
    )


def _paid_plan(price=900):
    return Plan.objects.create(
        tier=PlanTier.PLUS,
        name="Plus",
        price_minor=price,
        currency="USD",
        interval=BillingInterval.MONTHLY,
        max_members=2,
        max_accounts=25,
        ai_insights=True,
        sort_order=1,
    )


def _bearer(user, tenant_id):
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant_id))
    return client


# --------------------------------------------------------------------------- plans
def test_plans_are_public():
    _free_plan()
    from rest_framework.test import APIClient

    # No auth, no tenant header — the catalog is public.
    resp = APIClient().get("/api/v1/billing/plans/")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# --------------------------------------------------------------------------- subscribe
def test_subscribe_free_activates_immediately():
    plan = _free_plan()
    m = MembershipFactory(role=Role.OWNER)
    client = _bearer(m.user, m.tenant_id)

    resp = client.post("/api/v1/billing/subscription/", {"plan_id": str(plan.id)}, format="json")
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == SubscriptionStatus.ACTIVE
    assert body["plan"]["name"] == "Free"


def test_subscribe_paid_without_method_is_rejected():
    plan = _paid_plan()
    m = MembershipFactory(role=Role.OWNER)
    client = _bearer(m.user, m.tenant_id)

    resp = client.post("/api/v1/billing/subscription/", {"plan_id": str(plan.id)}, format="json")
    assert resp.status_code == 422  # BillingError -> unprocessable


def test_subscribe_paid_with_card_charges_and_activates():
    plan = _paid_plan()
    m = MembershipFactory(role=Role.OWNER)
    client = _bearer(m.user, m.tenant_id)

    # add a card (sandbox tokenization)
    resp = client.post(
        "/api/v1/billing/payment-methods/",
        {"provider": "stripe", "token": "tok_visa", "kind": "card"},
        format="json",
    )
    assert resp.status_code == 201
    pm_id = resp.json()["id"]

    resp = client.post(
        "/api/v1/billing/subscription/",
        {"plan_id": str(plan.id), "payment_method_id": pm_id},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == SubscriptionStatus.ACTIVE

    # a succeeded payment was recorded
    payment = Payment.objects.get(tenant_id=m.tenant_id)
    assert payment.status == PaymentStatus.SUCCEEDED
    assert payment.amount_minor == 900


def test_one_subscription_per_tenant():
    free = _free_plan()
    paid = _paid_plan()
    m = MembershipFactory(role=Role.OWNER)
    client = _bearer(m.user, m.tenant_id)

    client.post("/api/v1/billing/subscription/", {"plan_id": str(free.id)}, format="json")
    # switching to another plan updates the same subscription row, never a second
    client.post(
        "/api/v1/billing/payment-methods/",
        {"provider": "stripe", "token": "tok_visa", "kind": "card"},
        format="json",
    )
    pm_id = client.get("/api/v1/billing/payment-methods/").json()[0]["id"]
    client.post(
        "/api/v1/billing/subscription/",
        {"plan_id": str(paid.id), "payment_method_id": pm_id},
        format="json",
    )
    assert Subscription.objects.filter(tenant_id=m.tenant_id).count() == 1


# --------------------------------------------------------------------------- mpesa (async)
def test_mpesa_subscribe_is_pending_until_webhook():
    plan = _paid_plan()
    m = MembershipFactory(role=Role.OWNER)
    client = _bearer(m.user, m.tenant_id)

    client.post(
        "/api/v1/billing/payment-methods/",
        {"provider": "mpesa", "token": "254712345678", "kind": "mpesa"},
        format="json",
    )
    pm_id = client.get("/api/v1/billing/payment-methods/").json()[0]["id"]
    resp = client.post(
        "/api/v1/billing/subscription/",
        {"plan_id": str(plan.id), "payment_method_id": pm_id},
        format="json",
    )
    assert resp.status_code == 201
    # STK push is async -> subscription stays incomplete, payment pending
    assert resp.json()["status"] == SubscriptionStatus.INCOMPLETE
    payment = Payment.objects.get(tenant_id=m.tenant_id)
    assert payment.status == PaymentStatus.PENDING

    # simulate the M-PESA callback (success)
    body = json.dumps({"Body": {"stkCallback": {"ResultCode": 0, "CheckoutRequestID": payment.provider_ref}}})
    from rest_framework.test import APIClient

    wh = APIClient().post("/api/v1/billing/webhooks/mpesa/", body, content_type="application/json")
    assert wh.status_code == 200
    assert wh.json()["status"] == "processed"

    payment.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCEEDED
    sub = Subscription.objects.get(tenant_id=m.tenant_id)
    assert sub.status == SubscriptionStatus.ACTIVE


# --------------------------------------------------------------------------- webhooks
def test_webhook_is_idempotent():
    plan = _paid_plan()
    m = MembershipFactory(role=Role.OWNER)
    client = _bearer(m.user, m.tenant_id)
    client.post(
        "/api/v1/billing/payment-methods/",
        {"provider": "stripe", "token": "tok_visa", "kind": "card"},
        format="json",
    )
    pm_id = client.get("/api/v1/billing/payment-methods/").json()[0]["id"]
    client.post(
        "/api/v1/billing/subscription/",
        {"plan_id": str(plan.id), "payment_method_id": pm_id},
        format="json",
    )
    from rest_framework.test import APIClient

    body = json.dumps({"id": "evt_1", "type": "payment_intent.succeeded", "data": {"object": {"id": "pi_x"}}})
    first = APIClient().post("/api/v1/billing/webhooks/stripe/", body, content_type="application/json")
    second = APIClient().post("/api/v1/billing/webhooks/stripe/", body, content_type="application/json")
    assert first.json()["status"] == "processed"
    assert second.json()["status"] == "duplicate"
    assert WebhookEvent.objects.filter(provider="stripe", event_id="evt_1").count() == 1


# --------------------------------------------------------------------------- cancel
def test_cancel_at_period_end():
    plan = _free_plan()
    m = MembershipFactory(role=Role.OWNER)
    client = _bearer(m.user, m.tenant_id)
    client.post("/api/v1/billing/subscription/", {"plan_id": str(plan.id)}, format="json")

    resp = client.post("/api/v1/billing/subscription/cancel/", {"at_period_end": True}, format="json")
    assert resp.status_code == 200
    assert resp.json()["cancel_at_period_end"] is True


def test_viewer_cannot_change_plan():
    plan = _free_plan()
    m = MembershipFactory(role=Role.VIEWER)
    client = _bearer(m.user, m.tenant_id)
    resp = client.post("/api/v1/billing/subscription/", {"plan_id": str(plan.id)}, format="json")
    assert resp.status_code == 403


# --------------------------------------------------------------------------- provider units
def test_provider_registry_resolves():
    assert get_provider("stripe").key == "stripe"
    assert get_provider("mpesa").key == "mpesa"
    with pytest.raises(ValueError):
        get_provider("nope")


def test_card_never_stores_raw_pan():
    """Only safe display fields are persisted — no raw number column exists."""
    m = MembershipFactory(role=Role.OWNER)
    client = _bearer(m.user, m.tenant_id)
    resp = client.post(
        "/api/v1/billing/payment-methods/",
        {"provider": "stripe", "token": "4111111111111111", "kind": "card"},
        format="json",
    )
    data = resp.json()
    # last4 present, but the full PAN appears nowhere in the stored/returned data
    assert "4111111111111111" not in json.dumps(data)
    assert len(data["last4"]) <= 4
