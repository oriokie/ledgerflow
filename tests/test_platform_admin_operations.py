"""Platform workspace: tenant operations, impersonation and SaaS metrics.

The impersonation tests carry the most weight here — it is the only path by
which platform staff can reach customer financial data, so its limits are
tested as guarantees rather than as behaviour.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.billing import services as billing
from apps.billing.models import (
    BillingInterval,
    Payment,
    PaymentStatus,
    Plan,
    PlanTier,
    Subscription,
    SubscriptionStatus,
)
from apps.platform_admin import metrics
from apps.platform_admin.models import (
    ImpersonationGrant,
    ImpersonationStatus,
    PlatformAuditLog,
)
from apps.platform_admin.rbac import PlatformRole
from apps.platform_admin.selectors import tenants as tenant_selectors
from apps.platform_admin.services import impersonation as impersonation_service
from apps.platform_admin.services import tenants as tenant_service
from apps.tenancy.models import Tenant
from tests.factories import MembershipFactory
from tests.test_platform_admin_rbac import client_for, make_staff

pytestmark = pytest.mark.django_db


def _plan(price=1000, currency="USD", interval=BillingInterval.MONTHLY, tier=PlanTier.PLUS, name=None):
    """Get-or-create a plan.

    `Plan` is unique on (tier, interval, currency), so tests that want two
    plans at different prices must vary one of those — the catalog genuinely
    cannot hold two monthly USD Plus plans.
    """
    plan, created = Plan.objects.get_or_create(
        tier=tier,
        interval=interval,
        currency=currency,
        defaults={"name": name or f"{tier}-{interval}-{currency}", "price_minor": price},
    )
    if not created and plan.price_minor != price:
        plan.price_minor = price
        plan.save(update_fields=["price_minor"])
    return plan


def _paying_tenant(
    price=1000,
    currency="USD",
    interval=BillingInterval.MONTHLY,
    country="KE",
    tier=PlanTier.PLUS,
):
    membership = MembershipFactory()
    Tenant.objects.filter(id=membership.tenant_id).update(country=country)
    plan = _plan(price=price, currency=currency, interval=interval, tier=tier)
    Subscription.objects.create(
        tenant_id=membership.tenant_id,
        plan=plan,
        status=SubscriptionStatus.ACTIVE,
        current_period_start=timezone.now(),
        current_period_end=timezone.now() + timedelta(days=30),
    )
    return membership, plan


# ============================================================ tenant lifecycle
def test_suspending_a_workspace_requires_a_reason():
    owner = make_staff(PlatformRole.OWNER)
    membership = MembershipFactory()
    tenant = Tenant.objects.get(id=membership.tenant_id)

    with pytest.raises(tenant_service.TenantAdminError):
        tenant_service.suspend(tenant=tenant, actor=owner, reason="x")


def test_suspension_revokes_access_without_touching_data():
    owner = make_staff(PlatformRole.OWNER)
    membership = MembershipFactory()
    tenant = Tenant.objects.get(id=membership.tenant_id)

    tenant_service.suspend(tenant=tenant, actor=owner, reason="Confirmed chargeback fraud")

    tenant.refresh_from_db()
    assert not tenant.is_active
    # Nothing is deleted — suspension must be losslessly reversible.
    assert Tenant.objects.filter(id=tenant.id).exists()
    assert tenant.memberships.count() == 1


def test_suspension_is_idempotent():
    owner = make_staff(PlatformRole.OWNER)
    tenant = Tenant.objects.get(id=MembershipFactory().tenant_id)

    tenant_service.suspend(tenant=tenant, actor=owner, reason="First suspension")
    tenant_service.suspend(tenant=tenant, actor=owner, reason="Second attempt")

    assert PlatformAuditLog.objects.filter(action="tenant.suspended").count() == 1


def test_reactivation_restores_access():
    owner = make_staff(PlatformRole.OWNER)
    tenant = Tenant.objects.get(id=MembershipFactory().tenant_id)

    tenant_service.suspend(tenant=tenant, actor=owner, reason="Investigating abuse report")
    tenant_service.reactivate(tenant=tenant, actor=owner, reason="Investigation cleared them")

    tenant.refresh_from_db()
    assert tenant.is_active


def test_a_generic_edit_cannot_flip_active_state():
    """is_active has its own audited operation; a generic edit must not bypass it."""
    owner = make_staff(PlatformRole.OWNER)
    tenant = Tenant.objects.get(id=MembershipFactory().tenant_id)

    with pytest.raises(tenant_service.TenantAdminError):
        tenant_service.update_tenant(tenant=tenant, actor=owner, is_active=False)


def test_editing_a_tenant_records_only_what_changed():
    owner = make_staff(PlatformRole.OWNER)
    tenant = Tenant.objects.get(id=MembershipFactory().tenant_id)

    tenant_service.update_tenant(
        tenant=tenant, actor=owner, name="Renamed Household", reason="Customer request"
    )
    row = PlatformAuditLog.objects.get(action="tenant.updated")
    assert set(row.changes) == {"name"}


def test_closing_a_workspace_emits_a_purge_event_rather_than_deleting():
    """Irreversible erasure stays a deliberate asynchronous step."""
    from apps.common.outbox import OutboxEvent

    owner = make_staff(PlatformRole.OWNER)
    tenant = Tenant.objects.get(id=MembershipFactory().tenant_id)

    tenant_service.close_tenant(tenant=tenant, actor=owner, reason="Customer asked us to close it")

    assert Tenant.objects.filter(id=tenant.id).exists()
    assert OutboxEvent.objects.filter(
        aggregate_id=tenant.id, event_type="tenancy.workspace.closed"
    ).exists()


# ============================================================== subscriptions
def test_extending_a_lapsed_trial_gives_a_real_extension():
    """Extending from a past date would produce an end date still in the past."""
    owner = make_staff(PlatformRole.OWNER)
    membership = MembershipFactory()
    tenant = Tenant.objects.get(id=membership.tenant_id)
    Subscription.objects.create(
        tenant_id=tenant.id,
        plan=_plan(),
        status=SubscriptionStatus.TRIALING,
        trial_end=timezone.now() - timedelta(days=30),
    )

    sub = tenant_service.extend_trial(
        tenant=tenant, actor=owner, days=7, reason="Sales asked for more evaluation time"
    )
    assert sub.trial_end > timezone.now() + timedelta(days=6)


def test_a_complimentary_subscription_takes_no_payment_method():
    owner = make_staff(PlatformRole.OWNER)
    tenant = Tenant.objects.get(id=MembershipFactory().tenant_id)
    plan = _plan(price=5000)

    sub = tenant_service.grant_complimentary(
        tenant=tenant, plan=plan, actor=owner, reason="Design partner agreement", months=6
    )

    assert sub.status == SubscriptionStatus.ACTIVE
    assert sub.metadata["complimentary"] is True
    assert Payment.objects.filter(tenant_id=tenant.id).count() == 0


def test_changing_to_a_paid_plan_without_a_card_is_refused_with_a_useful_message():
    owner = make_staff(PlatformRole.OWNER)
    tenant = Tenant.objects.get(id=MembershipFactory().tenant_id)

    with pytest.raises(tenant_service.TenantAdminError, match="complimentary"):
        tenant_service.change_plan(
            tenant=tenant, plan=_plan(price=5000), actor=owner, reason="Upgrade requested by phone"
        )


def test_resetting_billing_state_closes_dunning_and_restores_access():
    from apps.billing.dunning import ensure_default_policy, open_case
    from apps.billing.dunning_models import DunningCase, DunningCaseStatus

    owner = make_staff(PlatformRole.OWNER)
    membership = MembershipFactory()
    tenant = Tenant.objects.get(id=membership.tenant_id)
    ensure_default_policy()
    sub = Subscription.objects.create(
        tenant_id=tenant.id, plan=_plan(), status=SubscriptionStatus.PAST_DUE
    )
    open_case(subscription=sub)
    tenant.is_active = False
    tenant.save(update_fields=["is_active"])

    tenant_service.reset_billing_state(
        tenant=tenant, actor=owner, reason="Provider outage double-charged them"
    )

    tenant.refresh_from_db()
    sub.refresh_from_db()
    assert tenant.is_active
    assert sub.status == SubscriptionStatus.ACTIVE
    assert DunningCase.objects.get(subscription=sub).status == DunningCaseStatus.CANCELLED


def test_resetting_billing_state_moves_no_money():
    """The support escape hatch changes state, never money."""
    owner = make_staff(PlatformRole.OWNER)
    tenant = Tenant.objects.get(id=MembershipFactory().tenant_id)
    Subscription.objects.create(tenant_id=tenant.id, plan=_plan(), status=SubscriptionStatus.PAST_DUE)

    tenant_service.reset_billing_state(tenant=tenant, actor=owner, reason="Stuck after a provider blip")

    assert Payment.objects.filter(tenant_id=tenant.id).count() == 0


# ============================================================== impersonation
def test_impersonation_demands_a_specific_reason():
    """'support' is indistinguishable from no reason when reviewed later."""
    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    membership = MembershipFactory()

    with pytest.raises(impersonation_service.ImpersonationError):
        impersonation_service.start(
            staff=staff, tenant_id=membership.tenant_id, reason="support"
        )


def test_impersonation_requires_the_capability():
    auditor = make_staff(PlatformRole.AUDITOR)
    membership = MembershipFactory()

    with pytest.raises(impersonation_service.ImpersonationError):
        impersonation_service.start(
            staff=auditor,
            tenant_id=membership.tenant_id,
            reason="Investigating a reported balance discrepancy",
        )


def test_the_raw_token_is_never_stored():
    """A database dump must not yield a usable impersonation credential."""
    import hashlib

    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    membership = MembershipFactory()
    grant, raw = impersonation_service.start(
        staff=staff,
        tenant_id=membership.tenant_id,
        reason="Investigating a reported balance discrepancy",
    )

    assert raw not in grant.token_hash
    assert grant.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert not ImpersonationGrant.objects.filter(token_hash=raw).exists()


def test_an_expired_grant_is_unusable_and_marked_expired():
    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    membership = MembershipFactory()
    grant, raw = impersonation_service.start(
        staff=staff, tenant_id=membership.tenant_id, reason="Checking a duplicated transaction"
    )
    grant.expires_at = timezone.now() - timedelta(minutes=1)
    grant.save(update_fields=["expires_at"])

    with pytest.raises(impersonation_service.ImpersonationError):
        impersonation_service.resolve(raw_token=raw)

    grant.refresh_from_db()
    assert grant.status == ImpersonationStatus.EXPIRED


def test_a_revoked_grant_stops_working_immediately():
    """A JWT claim could not offer this; a re-read grant can."""
    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    owner = make_staff(PlatformRole.OWNER)
    membership = MembershipFactory()
    grant, raw = impersonation_service.start(
        staff=staff, tenant_id=membership.tenant_id, reason="Checking a duplicated transaction"
    )
    assert impersonation_service.resolve(raw_token=raw) is not None

    impersonation_service.revoke(grant=grant, actor=owner, reason="Session no longer warranted")

    with pytest.raises(impersonation_service.ImpersonationError):
        impersonation_service.resolve(raw_token=raw)


def test_revoking_platform_access_ends_live_impersonations():
    """Otherwise revocation is cosmetic until the session happens to expire."""
    from apps.platform_admin.services import staff as staff_service

    operator = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    owner = make_staff(PlatformRole.OWNER)
    membership = MembershipFactory()
    grant, _ = impersonation_service.start(
        staff=operator, tenant_id=membership.tenant_id, reason="Investigating a sync failure"
    )

    staff_service.revoke(staff=operator, actor=owner, reason="Left the company")

    grant.refresh_from_db()
    assert grant.status == ImpersonationStatus.REVOKED


def test_impersonation_binds_real_tenant_context_not_a_bypass():
    """Impersonated reads go through the same RLS policy a member's would."""
    from apps.common.tenant_context import get_current_tenant_id

    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    membership = MembershipFactory()
    grant, _ = impersonation_service.start(
        staff=staff, tenant_id=membership.tenant_id, reason="Reproducing a reported import bug"
    )

    with impersonation_service.impersonate(grant=grant):
        assert get_current_tenant_id() == membership.tenant_id

    assert get_current_tenant_id() is None


def test_impersonation_cannot_reach_a_different_tenant():
    """The grant names one workspace, and RLS enforces that, not the app."""
    from apps.finance.models import Category

    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    target = MembershipFactory()
    other = MembershipFactory()
    grant, _ = impersonation_service.start(
        staff=staff, tenant_id=target.tenant_id, reason="Reproducing a reported import bug"
    )

    with impersonation_service.impersonate(grant=grant):
        visible = set(Category.unscoped.values_list("tenant_id", flat=True))

    assert other.tenant_id not in visible


def test_impersonation_counts_its_own_use():
    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    membership = MembershipFactory()
    grant, _ = impersonation_service.start(
        staff=staff, tenant_id=membership.tenant_id, reason="Reproducing a reported import bug"
    )

    for _ in range(3):
        with impersonation_service.impersonate(grant=grant):
            pass

    grant.refresh_from_db()
    assert grant.request_count == 3


def test_starting_a_second_session_supersedes_the_first():
    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    membership = MembershipFactory()
    first, _ = impersonation_service.start(
        staff=staff, tenant_id=membership.tenant_id, reason="Reproducing a reported import bug"
    )
    impersonation_service.start(
        staff=staff, tenant_id=membership.tenant_id, reason="Reproducing a reported import bug again"
    )

    first.refresh_from_db()
    assert first.status == ImpersonationStatus.ENDED
    assert impersonation_service.active_sessions().count() == 1


def test_impersonation_is_read_only_unless_stated():
    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    membership = MembershipFactory()
    grant, _ = impersonation_service.start(
        staff=staff, tenant_id=membership.tenant_id, reason="Reproducing a reported import bug"
    )
    assert grant.read_only is True


def test_starting_impersonation_is_audited_with_the_reason():
    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    membership = MembershipFactory()
    impersonation_service.start(
        staff=staff,
        tenant_id=membership.tenant_id,
        reason="Customer reports a missing March statement",
    )

    row = PlatformAuditLog.objects.get(action="impersonation.started")
    assert row.tenant_id == membership.tenant_id
    assert "March statement" in row.reason


def test_stale_grants_are_swept():
    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    membership = MembershipFactory()
    grant, _ = impersonation_service.start(
        staff=staff, tenant_id=membership.tenant_id, reason="Reproducing a reported import bug"
    )
    ImpersonationGrant.objects.filter(pk=grant.pk).update(
        expires_at=timezone.now() - timedelta(hours=1)
    )

    assert impersonation_service.expire_stale() == 1
    grant.refresh_from_db()
    assert grant.status == ImpersonationStatus.EXPIRED


def test_impersonation_endpoint_returns_the_token_exactly_once():
    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    membership = MembershipFactory()
    response = client_for(staff).post(
        f"/api/v1/platform/tenants/{membership.tenant_id}/impersonate/",
        {"reason": "Customer reports a missing March statement"},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["token"]

    listing = client_for(staff).get("/api/v1/platform/impersonations/").json()
    assert "token" not in listing["results"][0]


# ===================================================================== metrics
def test_mrr_normalises_an_annual_plan_to_a_monthly_figure():
    """Otherwise MRR spikes every January and stops being a run-rate."""
    _paying_tenant(price=12_000, interval=BillingInterval.YEARLY)
    assert metrics.recurring_revenue(currency="USD").mrr_minor == 1000


def test_arr_is_twelve_times_mrr():
    _paying_tenant(price=1000)
    revenue = metrics.recurring_revenue(currency="USD")
    assert revenue.arr_minor == revenue.mrr_minor * 12


def test_complimentary_subscriptions_are_excluded_from_mrr():
    """A comp is real usage and zero revenue; counting it inflates MRR."""
    owner = make_staff(PlatformRole.OWNER)
    tenant = Tenant.objects.get(id=MembershipFactory().tenant_id)
    tenant_service.grant_complimentary(
        tenant=tenant, plan=_plan(price=9900), actor=owner, reason="Design partner agreement"
    )
    assert metrics.recurring_revenue(currency="USD").mrr_minor == 0


def test_free_plans_do_not_drag_arpa_toward_zero():
    _paying_tenant(price=2000)
    free_tenant = MembershipFactory()
    Subscription.objects.create(
        tenant_id=free_tenant.tenant_id,
        plan=_plan(price=0, tier=PlanTier.FREE, name="Free"),
        status=SubscriptionStatus.ACTIVE,
    )
    revenue = metrics.recurring_revenue(currency="USD")
    assert revenue.paying_customers == 1
    assert revenue.arpa_minor == 2000


def test_trialing_subscriptions_are_not_counted_as_revenue():
    membership = MembershipFactory()
    Subscription.objects.create(
        tenant_id=membership.tenant_id,
        plan=_plan(price=5000),
        status=SubscriptionStatus.TRIALING,
        trial_end=timezone.now() + timedelta(days=7),
    )
    assert metrics.recurring_revenue(currency="USD").mrr_minor == 0


def test_mrr_is_reported_per_currency_not_summed_across_them():
    """Summing needs an FX rate, which would make history move when rates do."""
    _paying_tenant(price=1000, currency="USD")
    _paying_tenant(price=50_000, currency="KES")

    assert metrics.recurring_revenue(currency="USD").mrr_minor == 1000
    assert metrics.recurring_revenue(currency="KES").mrr_minor == 50_000


def test_collected_revenue_subtracts_refunds():
    from apps.billing import refunds as refund_service
    from tests.factories import UserFactory

    membership = MembershipFactory()
    payment = Payment.objects.create(
        tenant_id=membership.tenant_id,
        amount_minor=1000,
        currency="USD",
        status=PaymentStatus.SUCCEEDED,
        provider="stripe",
        provider_ref="pi_test_refunded",
    )
    refund = refund_service.request_refund(
        payment=payment, amount_minor=400, reason="Partial goodwill", requested_by=UserFactory()
    )
    refund_service.approve_refund(refund=refund, approved_by=UserFactory())

    totals = metrics.collected_revenue(
        start=timezone.now() - timedelta(days=1), end=timezone.now() + timedelta(days=1)
    )
    assert totals["gross_minor"] == 1000
    assert totals["refunded_minor"] == 400
    assert totals["net_minor"] == 600


def test_ltv_is_null_rather_than_infinite_when_nothing_has_churned():
    """A fabricated LTV would be quoted as if it meant something."""
    _paying_tenant(price=1000)
    assert metrics.lifetime_value(currency="USD")["ltv_minor"] is None


def test_churn_counts_cancellations_in_the_window():
    membership, plan = _paying_tenant(price=1000)
    old = MembershipFactory()
    Subscription.objects.create(
        tenant_id=old.tenant_id,
        plan=plan,
        status=SubscriptionStatus.CANCELED,
        canceled_at=timezone.now() - timedelta(days=3),
    )
    result = metrics.churn(days=30)
    assert result["churned"] == 1
    assert result["rate"] > 0


def test_revenue_by_country_falls_back_to_the_locale_region():
    """Workspaces predating the country field still report somewhere real."""
    membership, _ = _paying_tenant(price=1000, country="")
    Tenant.objects.filter(id=membership.tenant_id).update(default_locale="en-GB")

    rows = metrics.revenue_by("country", currency="USD")
    assert rows[0]["key"] == "GB"


def test_revenue_by_plan_groups_and_sorts_by_size():
    _paying_tenant(price=500, tier=PlanTier.PLUS)
    _paying_tenant(price=9000, tier=PlanTier.BUSINESS)
    rows = metrics.revenue_by("plan", currency="USD")
    assert rows[0]["mrr_minor"] == 9000


def test_trial_conversion_excludes_trials_still_running():
    """Counting a trial with three days left as a failure understates conversion."""
    running = MembershipFactory()
    Subscription.objects.create(
        tenant_id=running.tenant_id,
        plan=_plan(price=1000),
        status=SubscriptionStatus.TRIALING,
        trial_end=timezone.now() + timedelta(days=3),
    )
    result = metrics.trial_conversion(days=90)
    assert result["trials_concluded"] == 0
    assert result["still_running"] == 1
    assert result["conversion_rate"] is None


def test_forecast_is_labelled_as_an_extrapolation():
    """An operator deserves to know they are reading a projection."""
    _paying_tenant(price=1000)
    projection = metrics.forecast_revenue(months_ahead=3, currency="USD")
    assert len(projection) == 3
    assert "extrapolation" in projection[0]["basis"]


def test_the_dashboard_assembles_without_any_data():
    """A fresh install must not 500 on an empty database."""
    body = metrics.dashboard.uncached(currency="USD")
    assert body["revenue"]["mrr_minor"] == 0
    assert body["customers"]["tenants_total"] == 0


# =================================================================== directory
def test_the_tenant_directory_avoids_n_plus_one_queries(django_assert_num_queries):
    """Listing must cost a fixed number of queries regardless of page size."""
    for _ in range(6):
        _paying_tenant(price=1000)

    tenants = list(tenant_selectors.search_tenants()[:6])
    # Four bulk lookups: subscriptions, owners, last payments, usage snapshots.
    with django_assert_num_queries(4):
        rows = tenant_selectors.directory_page(tenants)
    assert len(rows) == 6


def test_the_directory_never_exposes_financial_content():
    """The console shows who the customer is and what they pay, never what
    they spend. Seeing that requires an audited impersonation grant."""
    membership, _ = _paying_tenant()
    row = tenant_selectors.directory_page(list(tenant_selectors.search_tenants()))[0]

    forbidden = {"balance", "transactions", "accounts", "categories", "net_worth"}
    assert not forbidden & set(row)


def test_the_directory_can_be_filtered_by_status_and_country():
    _paying_tenant(country="KE")
    suspended, _ = _paying_tenant(country="US", tier=PlanTier.FAMILY)
    Tenant.objects.filter(id=suspended.tenant_id).update(is_active=False)

    assert tenant_selectors.search_tenants(status="suspended").count() == 1
    assert tenant_selectors.search_tenants(country="KE").count() == 1


def test_the_directory_sort_key_is_an_allowlist():
    """A client must not be able to order by an unindexed column."""
    _paying_tenant()
    # An unknown key silently falls back rather than reaching order_by().
    assert tenant_selectors.search_tenants(order_by="-secret_column").count() == 1


def test_expiring_trials_lists_only_those_ending_soon():
    soon = MembershipFactory()
    later = MembershipFactory()
    plan = _plan(price=1000)
    Subscription.objects.create(
        tenant_id=soon.tenant_id,
        plan=plan,
        status=SubscriptionStatus.TRIALING,
        trial_end=timezone.now() + timedelta(days=3),
    )
    Subscription.objects.create(
        tenant_id=later.tenant_id,
        plan=plan,
        status=SubscriptionStatus.TRIALING,
        trial_end=timezone.now() + timedelta(days=40),
    )
    assert tenant_selectors.expiring_trials(within_days=7).count() == 1


# ======================================================================== api
def test_the_full_tenant_action_flow_over_http():
    owner = make_staff(PlatformRole.OWNER)
    membership = MembershipFactory()
    client = client_for(owner)
    base = f"/api/v1/platform/tenants/{membership.tenant_id}"

    assert client.get(f"{base}/").status_code == 200

    suspend = client.post(
        f"{base}/suspend/", {"reason": "Payment disputed by the cardholder"}, format="json"
    )
    assert suspend.status_code == 200
    assert suspend.json()["is_active"] is False

    reactivate = client.post(
        f"{base}/reactivate/", {"reason": "Dispute resolved in our favour"}, format="json"
    )
    assert reactivate.json()["is_active"] is True


def test_an_action_without_a_reason_is_a_400_with_a_field_error():
    """The UI attaches this to the textarea, so it must be a field error."""
    owner = make_staff(PlatformRole.OWNER)
    membership = MembershipFactory()
    response = client_for(owner).post(
        f"/api/v1/platform/tenants/{membership.tenant_id}/suspend/", {}, format="json"
    )
    assert response.status_code == 400
    assert "reason" in str(response.json())


def test_the_audit_endpoint_surfaces_recorded_actions():
    owner = make_staff(PlatformRole.OWNER)
    membership = MembershipFactory()
    client = client_for(owner)
    client.post(
        f"/api/v1/platform/tenants/{membership.tenant_id}/suspend/",
        {"reason": "Confirmed abuse of the free tier"},
        format="json",
    )

    body = client.get("/api/v1/platform/audit/").json()
    actions = [row["action"] for row in body["results"]]
    assert "tenant.suspended" in actions


def test_unknown_analytics_report_is_rejected_with_the_valid_options():
    owner = make_staff(PlatformRole.OWNER)
    response = client_for(owner).get("/api/v1/platform/analytics/?report=nonsense")
    assert response.status_code == 400
    assert "revenue_series" in response.json()["detail"]


def test_health_endpoint_never_500s_even_with_no_workers():
    """A health dashboard that errors has failed at the moment it was needed."""
    owner = make_staff(PlatformRole.OWNER)
    body = client_for(owner).get("/api/v1/platform/health/").json()

    assert body["status"] in {"ok", "degraded", "down"}
    names = {c["name"] for c in body["components"]}
    assert {"database", "cache", "queues", "storage", "outbox"} <= names


def test_ordinary_subscriptions_are_not_mistaken_for_complimentary_ones():
    """Regression: the comp exclusion once wiped out all revenue.

    `.exclude(metadata__complimentary=True)` also drops rows whose JSON has no
    `complimentary` key — SQL's three-valued logic makes `NOT (NULL = true)`
    evaluate to NULL, not TRUE. Since ordinary subscriptions carry `{}`, that
    excluded every one of them and reported zero MRR platform-wide.
    """
    membership, plan = _paying_tenant(price=2500)
    assert Subscription.objects.get(tenant_id=membership.tenant_id).metadata == {}
    assert metrics.recurring_revenue(currency="USD").mrr_minor == 2500
