"""The platform console's HTTP surface.

`platform_admin/api/views.py` sat at 51% with 302 uncovered statements — the
largest single hole in the codebase, and an instructive one: the *services* and
RBAC beneath it are heavily tested, because that is where I judged the risk to
be. The result was that the authorisation rules were proven and the wiring that
applies them substantially was not. Only 14 of 46 console endpoints appeared in
any test.

These are integration tests through the URL router, so they exercise the
capability gate, the serializer, the service call and the response shape
together — the four things a view is actually made of.
"""

from __future__ import annotations

import uuid

import pytest

from apps.billing import invoicing
from apps.billing.models import (
    BillingInterval,
    Payment,
    PaymentStatus,
    Plan,
    PlanTier,
    Subscription,
    SubscriptionStatus,
)
from apps.platform_admin.rbac import PlatformRole
from tests.factories import MembershipFactory, UserFactory
from tests.test_platform_admin_rbac import client_for, make_staff

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return make_staff(PlatformRole.OWNER)


@pytest.fixture
def api(owner):
    return client_for(owner)


def _plan(price=900, tier=PlanTier.PLUS, name="Plus"):
    return Plan.objects.create(
        tier=tier, name=name, price_minor=price, currency="USD",
        interval=BillingInterval.MONTHLY,
    )


def _invoice(tenant_id=None, status="pending"):
    inv = invoicing.create_invoice(
        tenant_id=tenant_id or uuid.uuid4(),
        currency="USD",
        line_items=[invoicing.LineItemSpec(description="Plus", amount_minor=900)],
        billing_email="customer@example.test",
    )
    if status != "draft":
        invoicing.issue_invoice(invoice=inv)
    return inv


# ==================================================================== reads
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/platform/me/",
        "/api/v1/platform/capabilities/",
        "/api/v1/platform/dashboard/",
        "/api/v1/platform/tenants/",
        "/api/v1/platform/plans/",
        "/api/v1/platform/subscriptions/",
        "/api/v1/platform/subscriptions/expiring-trials/",
        "/api/v1/platform/invoices/",
        "/api/v1/platform/payments/",
        "/api/v1/platform/refunds/",
        "/api/v1/platform/coupons/",
        "/api/v1/platform/dunning/cases/",
        "/api/v1/platform/dunning/policies/",
        "/api/v1/platform/staff/",
        "/api/v1/platform/audit/",
        "/api/v1/platform/health/",
        "/api/v1/platform/notifications/",
        "/api/v1/platform/impersonations/",
        "/api/v1/platform/saved-views/",
        "/api/v1/platform/settings/",
    ],
)
def test_every_console_read_endpoint_responds_on_an_empty_platform(api, path):
    """A fresh install must not 500 anywhere. Half these were never called by
    a test, so an empty-state crash would have reached an operator first."""
    response = api.get(path)
    assert response.status_code == 200, (path, response.status_code, response.data)


@pytest.mark.parametrize(
    "report",
    ["revenue_series", "cohorts", "forecast", "churn", "ltv", "trial_conversion",
     "payment_success", "by_plan", "by_country", "by_currency", "by_provider"],
)
def test_every_analytics_report_renders(api, report):
    response = api.get("/api/v1/platform/analytics/", {"report": report})
    assert response.status_code == 200, (report, response.data)
    assert response.data["report"] == report


def test_an_unknown_analytics_report_lists_the_valid_ones(api):
    response = api.get("/api/v1/platform/analytics/", {"report": "nope"})
    assert response.status_code == 400
    assert "revenue_series" in response.data["detail"]


def test_a_malformed_analytics_parameter_is_a_400_not_a_500(api):
    response = api.get("/api/v1/platform/analytics/", {"report": "churn", "days": "many"})
    assert response.status_code == 400


# ================================================================== tenants
def test_tenant_detail_and_edit(api):
    membership = MembershipFactory()
    base = f"/api/v1/platform/tenants/{membership.tenant_id}"

    assert api.get(f"{base}/").status_code == 200

    edited = api.patch(f"{base}/", {"name": "Renamed", "country": "ke"}, format="json")
    assert edited.status_code == 200
    assert edited.data["name"] == "Renamed"
    assert edited.data["country"] == "KE"


def test_a_generic_edit_cannot_suspend_a_workspace(api):
    """`is_active` has its own audited operation. A generic edit must not reach
    it, or a suspension would happen with no suspension audit row.

    The serializer drops unknown fields rather than rejecting them, which is
    DRF's default and is safe — so the assertion is on the outcome (the
    workspace is still active) rather than on the status code, which would be
    testing the framework's error style instead of the product's behaviour.
    """
    from apps.tenancy.models import Tenant

    membership = MembershipFactory()
    api.patch(
        f"/api/v1/platform/tenants/{membership.tenant_id}/",
        {"is_active": False, "name": "Renamed"},
        format="json",
    )
    tenant = Tenant.objects.get(id=membership.tenant_id)
    assert tenant.is_active is True, "a generic edit suspended a workspace"
    assert tenant.name == "Renamed", "the legitimate part of the edit was dropped"


def test_tenant_endpoints_404_on_an_unknown_workspace(api):
    missing = uuid.uuid4()
    assert api.get(f"/api/v1/platform/tenants/{missing}/").status_code == 404
    assert (
        api.post(
            f"/api/v1/platform/tenants/{missing}/suspend/",
            {"reason": "Investigating a report"},
            format="json",
        ).status_code
        == 404
    )


def test_changing_to_an_unknown_plan_is_a_404(api):
    membership = MembershipFactory()
    response = api.post(
        f"/api/v1/platform/tenants/{membership.tenant_id}/change-plan/",
        {"plan_id": str(uuid.uuid4()), "reason": "Upgrade requested by phone"},
        format="json",
    )
    assert response.status_code == 404


def test_granting_a_complimentary_subscription_over_http(api):
    membership = MembershipFactory()
    plan = _plan(price=4900, tier=PlanTier.BUSINESS, name="Business")
    response = api.post(
        f"/api/v1/platform/tenants/{membership.tenant_id}/complimentary/",
        {"plan_id": str(plan.id), "months": 6, "reason": "Design partner agreement"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["subscription"]["plan_name"] == "Business"


def test_issuing_credit_over_http(api):
    membership = MembershipFactory()
    response = api.post(
        f"/api/v1/platform/tenants/{membership.tenant_id}/credit/",
        {"amount_minor": 2500, "currency": "USD", "reason": "Outage compensation"},
        format="json",
    )
    assert response.status_code == 200


def test_extending_a_trial_over_http(api):
    membership = MembershipFactory()
    Subscription.objects.create(
        tenant_id=membership.tenant_id, plan=_plan(), status=SubscriptionStatus.TRIALING
    )
    response = api.post(
        f"/api/v1/platform/tenants/{membership.tenant_id}/extend-trial/",
        {"days": 14, "reason": "Sales asked for more evaluation time"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["subscription"]["trial_end"]


def test_resetting_billing_state_over_http(api):
    membership = MembershipFactory()
    Subscription.objects.create(
        tenant_id=membership.tenant_id, plan=_plan(), status=SubscriptionStatus.PAST_DUE
    )
    response = api.post(
        f"/api/v1/platform/tenants/{membership.tenant_id}/reset-billing/",
        {"reason": "Stuck after a provider outage"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["subscription"]["status"] == SubscriptionStatus.ACTIVE


# ================================================================= invoices
def test_voiding_an_invoice_over_http(api):
    invoice = _invoice()
    response = api.post(
        f"/api/v1/platform/invoices/{invoice.id}/void/",
        {"reason": "Billed in error"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["status"] == "cancelled"


def test_voiding_a_paid_invoice_is_refused(api):
    invoice = _invoice()
    invoicing.mark_paid(invoice=invoice)
    response = api.post(
        f"/api/v1/platform/invoices/{invoice.id}/void/",
        {"reason": "Changed my mind"},
        format="json",
    )
    assert response.status_code == 422


def test_invoice_detail_and_pdf(api):
    invoice = _invoice()
    detail = api.get(f"/api/v1/platform/invoices/{invoice.id}/")
    assert detail.status_code == 200
    assert detail.data["number"] == invoice.number

    pdf = api.get(f"/api/v1/platform/invoices/{invoice.id}/pdf/")
    assert pdf["Content-Type"] == "application/pdf"


def test_invoice_filters_narrow_the_list(api):
    tenant = uuid.uuid4()
    _invoice(tenant_id=tenant)
    _invoice()
    scoped = api.get("/api/v1/platform/invoices/", {"tenant_id": str(tenant)})
    assert scoped.data["count"] == 1


# ============================================================ reconciliation
def test_manual_payment_reconciliation_over_http(api):
    invoice = _invoice()
    payment = Payment.objects.create(
        tenant_id=invoice.tenant_id, amount_minor=invoice.total_minor, currency="USD",
        status=PaymentStatus.SUCCEEDED, provider="stripe", provider_ref="pi_manual",
    )
    response = api.post(
        "/api/v1/platform/payments/reconcile/",
        {"payment_id": str(payment.id), "invoice_id": str(invoice.id),
         "reason": "Bank transfer received out of band"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["status"] == "paid"


def test_reconciling_a_currency_mismatch_is_refused(api):
    invoice = _invoice()
    payment = Payment.objects.create(
        tenant_id=invoice.tenant_id, amount_minor=900, currency="KES",
        status=PaymentStatus.SUCCEEDED, provider="mpesa", provider_ref="ws_x",
    )
    response = api.post(
        "/api/v1/platform/payments/reconcile/",
        {"payment_id": str(payment.id), "invoice_id": str(invoice.id), "reason": "Manual match"},
        format="json",
    )
    assert response.status_code == 422


# ================================================================== refunds
def test_the_refund_request_and_approval_split_over_http():
    """Separation of duties end to end: Customer Success requests, Finance
    approves, and neither can do the other's half."""
    requester = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    approver = make_staff(PlatformRole.FINANCE)
    payment = Payment.objects.create(
        tenant_id=uuid.uuid4(), amount_minor=1000, currency="USD",
        status=PaymentStatus.SUCCEEDED, provider="stripe", provider_ref="pi_refundable",
    )

    requested = client_for(requester).post(
        "/api/v1/platform/refunds/",
        {"payment_id": str(payment.id), "amount_minor": 400, "reason": "Service outage"},
        format="json",
    )
    assert requested.status_code == 201

    # The requester cannot release the money.
    blocked = client_for(requester).post(
        f"/api/v1/platform/refunds/{requested.data['id']}/approve/", {}, format="json"
    )
    assert blocked.status_code == 403

    approved = client_for(approver).post(
        f"/api/v1/platform/refunds/{requested.data['id']}/approve/",
        {"note": "Verified the outage window"},
        format="json",
    )
    assert approved.status_code == 200
    assert approved.data["status"] == "succeeded"


def test_rejecting_a_refund_over_http():
    requester = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    approver = make_staff(PlatformRole.FINANCE)
    payment = Payment.objects.create(
        tenant_id=uuid.uuid4(), amount_minor=1000, currency="USD",
        status=PaymentStatus.SUCCEEDED, provider="stripe", provider_ref="pi_reject",
    )
    requested = client_for(requester).post(
        "/api/v1/platform/refunds/",
        {"payment_id": str(payment.id), "reason": "Customer asked"},
        format="json",
    )
    rejected = client_for(approver).post(
        f"/api/v1/platform/refunds/{requested.data['id']}/reject/",
        {"note": "Outside the refund window"},
        format="json",
    )
    assert rejected.status_code == 200
    assert rejected.data["status"] == "rejected"


def test_refunding_an_unknown_payment_is_a_404(api):
    response = api.post(
        "/api/v1/platform/refunds/",
        {"payment_id": str(uuid.uuid4()), "reason": "Nothing here"},
        format="json",
    )
    assert response.status_code == 404


# ================================================================== coupons
def test_coupon_lifecycle_over_http(api):
    created = api.post(
        "/api/v1/platform/coupons/",
        {"code": "spring25", "name": "Spring 25%", "kind": "percent", "value": 2500},
        format="json",
    )
    assert created.status_code == 201
    assert created.data["code"] == "SPRING25", "codes must normalise to uppercase"

    duplicate = api.post(
        "/api/v1/platform/coupons/",
        {"code": "SPRING25", "name": "Clash", "kind": "percent", "value": 1000},
        format="json",
    )
    assert duplicate.status_code == 400

    updated = api.patch(
        f"/api/v1/platform/coupons/{created.data['id']}/", {"is_active": False}, format="json"
    )
    assert updated.status_code == 200

    # Deactivate rather than delete — redemption history references it.
    assert api.delete(f"/api/v1/platform/coupons/{created.data['id']}/").status_code == 204


def test_an_impossible_coupon_is_rejected(api):
    over_100 = api.post(
        "/api/v1/platform/coupons/",
        {"code": "TOOMUCH", "name": "x", "kind": "percent", "value": 20_000},
        format="json",
    )
    assert over_100.status_code == 400

    no_currency = api.post(
        "/api/v1/platform/coupons/",
        {"code": "FIXED", "name": "x", "kind": "fixed", "value": 500},
        format="json",
    )
    assert no_currency.status_code == 400


# ================================================================== dunning
def test_dunning_case_actions_over_http(api):
    from apps.billing import dunning

    membership = MembershipFactory()
    dunning.ensure_default_policy()
    sub = Subscription.objects.create(
        tenant_id=membership.tenant_id, plan=_plan(), status=SubscriptionStatus.PAST_DUE
    )
    case = dunning.open_case(subscription=sub)

    response = api.post(
        f"/api/v1/platform/dunning/cases/{case.id}/recover/",
        {"reason": "Customer paid by bank transfer"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["status"] == "recovered"


def test_an_unknown_dunning_action_is_rejected(api):
    from apps.billing import dunning

    membership = MembershipFactory()
    dunning.ensure_default_policy()
    sub = Subscription.objects.create(
        tenant_id=membership.tenant_id, plan=_plan(), status=SubscriptionStatus.PAST_DUE
    )
    case = dunning.open_case(subscription=sub)
    response = api.post(
        f"/api/v1/platform/dunning/cases/{case.id}/explode/",
        {"reason": "Testing the router"},
        format="json",
    )
    assert response.status_code == 400


def test_creating_a_dunning_policy_over_http(api):
    response = api.post(
        "/api/v1/platform/dunning/policies/",
        {"name": "Patient", "retry_offsets_days": [2, 5], "grace_period_days": 10,
         "suspend_after_days": 20, "abandon_after_days": 40, "is_default": True},
        format="json",
    )
    assert response.status_code == 201


def test_an_impossible_dunning_policy_is_refused(api):
    """Suspension before the grace period ends cannot happen in that order."""
    response = api.post(
        "/api/v1/platform/dunning/policies/",
        {"name": "Backwards", "retry_offsets_days": [1], "grace_period_days": 30,
         "suspend_after_days": 5, "abandon_after_days": 60},
        format="json",
    )
    assert response.status_code == 422


# ==================================================================== staff
def test_appointing_and_revoking_staff_over_http(api):
    user = UserFactory()
    appointed = api.post(
        "/api/v1/platform/staff/",
        {"email": user.email, "role": PlatformRole.FINANCE.value},
        format="json",
    )
    assert appointed.status_code == 201

    detail = api.get(f"/api/v1/platform/staff/{appointed.data['id']}/")
    assert detail.status_code == 200

    updated = api.patch(
        f"/api/v1/platform/staff/{appointed.data['id']}/",
        {"role": PlatformRole.AUDITOR.value, "reason": "Moved teams"},
        format="json",
    )
    assert updated.status_code == 200

    assert api.delete(f"/api/v1/platform/staff/{appointed.data['id']}/").status_code == 204


def test_appointing_an_unknown_email_is_a_field_error(api):
    response = api.post(
        "/api/v1/platform/staff/",
        {"email": "nobody@example.test", "role": PlatformRole.FINANCE.value},
        format="json",
    )
    assert response.status_code == 400
    assert "email" in response.data


# ========================================================== notifications
def test_acknowledging_notifications_over_http(api):
    from apps.platform_admin.notifications import raise_platform_alert

    alert = raise_platform_alert(category="test.alert", title="Something happened")
    single = api.post(f"/api/v1/platform/notifications/{alert.id}/ack/", {}, format="json")
    assert single.status_code == 200
    assert single.data["acknowledged_at"]

    raise_platform_alert(category="test.alert", title="Another", dedupe_key="two")
    bulk = api.post("/api/v1/platform/notifications/ack/", {}, format="json")
    assert bulk.status_code == 200
    assert bulk.data["acknowledged"] >= 1


# ============================================================ saved views
def test_saved_views_round_trip(api):
    created = api.post(
        "/api/v1/platform/saved-views/",
        {"surface": "tenants", "name": "Past due", "filters": {"status": "suspended"}},
        format="json",
    )
    assert created.status_code == 201

    listed = api.get("/api/v1/platform/saved-views/", {"surface": "tenants"})
    assert any(v["name"] == "Past due" for v in listed.data)

    assert api.delete(f"/api/v1/platform/saved-views/{created.data['id']}/").status_code == 204


# ========================================================== impersonation
def test_ending_someone_elses_session_needs_the_audit_capability():
    """Ending your own session is routine; ending another operator's is a
    supervisory act."""
    from apps.platform_admin.services import impersonation

    operator = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    other = make_staff(PlatformRole.TECHNICAL_SUPPORT)
    membership = MembershipFactory()
    grant, _ = impersonation.start(
        staff=operator, tenant_id=membership.tenant_id,
        reason="Investigating a reported import failure",
    )

    # Technical support holds audit.read, so it may supervise.
    response = client_for(other).post(
        f"/api/v1/platform/impersonations/{grant.id}/end/", {"reason": "No longer needed"},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["status"] in ("revoked", "ended")


def test_ending_an_unknown_session_is_a_404(api):
    response = api.post(
        f"/api/v1/platform/impersonations/{uuid.uuid4()}/end/", {}, format="json"
    )
    assert response.status_code == 404


def test_the_console_refuses_a_style_outside_the_allowed_set(api):
    """Validated at the boundary, not only in the store. The illustration style
    drives what every surface draws, so an accepted typo would blank the
    artwork everywhere — including the signed-out pages nobody is watching."""
    bad = api.post(
        "/api/v1/platform/settings/",
        {"key": "appearance.illustration_style", "value": "doodles", "reason": "typo"},
        format="json",
    )
    assert bad.status_code == 400, bad.data

    good = api.post(
        "/api/v1/platform/settings/",
        {"key": "appearance.illustration_style", "value": "doodle", "reason": "switching"},
        format="json",
    )
    assert good.status_code == 200, good.data
    assert good.data["value"] == "doodle"
    assert good.data["choices"] == ["clay", "doodle", "motion"]

    # The animated set goes through the same boundary. Asserted here rather
    # than trusted, because the console renders whatever `choices` says and a
    # style the store accepts but the API omits is a set nobody can select.
    animated = api.post(
        "/api/v1/platform/settings/",
        {"key": "appearance.illustration_style", "value": "motion", "reason": "trying it"},
        format="json",
    )
    assert animated.status_code == 200, animated.data
    assert animated.data["value"] == "motion"
