"""The plan catalogue as the console edits it and every surface reads it.

The property that matters most here: **one union, three surfaces**. The
entitlement enforcer, the public pricing payload and the console all resolve a
plan's features as tier-defaults ∪ row-overrides. A test that pinned only one
of them would let the others drift — so the round-trip test below drives the
console's PATCH and then asserts through the *public* endpoint and the
*enforcement* path.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.billing.models import Plan
from apps.billing.plan_catalogue import FEATURE_LABELS, UNIVERSAL, PlanFeature, resolved_features
from apps.platform_admin.models import PlatformAuditLog
from apps.platform_admin.rbac import PlatformRole
from tests.test_platform_admin_rbac import client_for, make_staff

pytestmark = pytest.mark.django_db

BASE = "/api/v1/platform/plans"


_ROLES = {
    "platform_owner": PlatformRole.OWNER,
    "billing_admin": PlatformRole.BILLING_ADMIN,
    "customer_success": PlatformRole.CUSTOMER_SUCCESS,
}


def _client(role="platform_owner") -> APIClient:
    return client_for(make_staff(_ROLES[role]))


def _plan(**overrides) -> Plan:
    defaults = dict(
        tier="plus",
        name="Plus",
        price_minor=700,
        currency="USD",
        interval="monthly",
        max_members=2,
        max_accounts=25,
        ai_insights=True,
    )
    return Plan.objects.create(**{**defaults, **overrides})


# ---------------------------------------------------------------- resolution
def test_resolved_features_are_tier_defaults_plus_override():
    plan = _plan(features=[str(PlanFeature.API_ACCESS)])
    resolved = resolved_features(plan)
    # Inherited from the tier…
    assert str(PlanFeature.GOALS) in resolved
    # …plus the one-off override that the tier does not include.
    assert str(PlanFeature.API_ACCESS) in resolved


def test_every_feature_has_a_label():
    """A new feature must never reach a pricing page as a bare slug.

    `label_for` has a readable fallback, but the fallback existing is not a
    licence to skip the label — this pins the map complete so adding a
    PlanFeature without naming it fails here, at author time.
    """
    for feature in PlanFeature:
        assert str(feature) in FEATURE_LABELS, f"{feature} has no label"
    for feature in UNIVERSAL:
        assert feature in FEATURE_LABELS, f"{feature} has no label"


# ------------------------------------------------------------------- console
def test_console_lists_plans_with_resolved_features_and_subscribers():
    _plan()
    response = _client().get(f"{BASE}/")
    assert response.status_code == 200
    row = response.data[0]
    assert row["subscriber_count"] == 0
    keys = {f["key"] for f in row["resolved_features"]}
    assert str(PlanFeature.GOALS) in keys
    # Labels ride along, so the console prints the same words as the landing.
    labels = {f["label"] for f in row["resolved_features"]}
    assert "Savings goals" in labels


def test_editing_features_flows_to_public_pricing_and_enforcement():
    """The round trip: console PATCH → public payload → entitlements."""
    plan = _plan()
    assert str(PlanFeature.API_ACCESS) not in resolved_features(plan)

    response = _client().patch(
        f"{BASE}/{plan.id}/",
        {"features": [str(PlanFeature.API_ACCESS)], "reason": "Plus pilot: API access"},
        format="json",
    )
    assert response.status_code == 200, response.data

    # Public pricing surface sees it…
    public = APIClient().get("/api/v1/billing/plans/?currency=USD")
    plus = next(p for p in public.data if p["id"] == str(plan.id))
    assert {"key": str(PlanFeature.API_ACCESS), "label": "API access"} in [
        {"key": f["key"], "label": f["label"]} for f in plus["resolved_features"]
    ]

    # …and the enforcement path resolves the same union.
    plan.refresh_from_db()
    assert str(PlanFeature.API_ACCESS) in resolved_features(plan)


def test_edit_requires_a_reason_and_lands_in_the_audit_log():
    plan = _plan()
    client = _client()

    missing = client.patch(f"{BASE}/{plan.id}/", {"price_minor": 900}, format="json")
    assert missing.status_code == 400

    response = client.patch(
        f"{BASE}/{plan.id}/",
        {"price_minor": 900, "reason": "Annual price review"},
        format="json",
    )
    assert response.status_code == 200
    entry = PlatformAuditLog.objects.filter(action="plan.updated").first()
    assert entry is not None
    assert entry.reason == "Annual price review"
    # Field-level before/after — the diff cannot be reconstructed later.
    assert entry.changes["price_minor"] == [700, 900]


def test_a_noop_edit_writes_no_audit_entry():
    plan = _plan()
    response = _client().patch(
        f"{BASE}/{plan.id}/",
        {"price_minor": 700, "reason": "No change at all"},
        format="json",
    )
    assert response.status_code == 200
    assert not PlatformAuditLog.objects.filter(action="plan.updated").exists()


def test_identity_fields_are_not_editable():
    """tier/interval/currency are the plan's identity; the serializer must
    silently drop them rather than reinterpret existing subscriptions."""
    plan = _plan()
    response = _client().patch(
        f"{BASE}/{plan.id}/",
        {"tier": "business", "currency": "EUR", "interval": "annual", "reason": "trying identity edit"},
        format="json",
    )
    assert response.status_code == 200
    plan.refresh_from_db()
    assert (plan.tier, plan.currency, plan.interval) == ("plus", "USD", "monthly")


def test_unknown_and_universal_features_are_rejected():
    plan = _plan()
    client = _client()

    unknown = client.patch(
        f"{BASE}/{plan.id}/",
        {"features": ["time_travel"], "reason": "testing validation"},
        format="json",
    )
    assert unknown.status_code == 400
    assert "Unknown features" in str(unknown.data)

    universal = client.patch(
        f"{BASE}/{plan.id}/",
        {"features": ["data_export"], "reason": "testing validation"},
        format="json",
    )
    assert universal.status_code == 400
    assert "universal" in str(universal.data).lower()


def test_plan_manage_is_its_own_grant():
    """Customer success can move a customer between plans; it cannot change
    what a plan *is*. The write needs plan.manage, not subscription.write."""
    plan = _plan()
    response = _client(role="customer_success").patch(
        f"{BASE}/{plan.id}/",
        {"price_minor": 100, "reason": "should be forbidden"},
        format="json",
    )
    assert response.status_code == 403
    # …but billing admin holds it.
    allowed = _client(role="billing_admin").patch(
        f"{BASE}/{plan.id}/",
        {"price_minor": 100, "reason": "billing admin price change"},
        format="json",
    )
    assert allowed.status_code == 200


def test_retired_plans_appear_only_with_all_flag():
    _plan(is_active=False, name="Legacy Plus")
    client = _client()
    assert all(p["is_active"] for p in client.get(f"{BASE}/").data)
    names = [p["name"] for p in client.get(f"{BASE}/?all=true").data]
    assert "Legacy Plus" in names
