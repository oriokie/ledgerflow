"""Two plans, one trial, and the teeth that make it commerce.

Basic keeps the books; Plus thinks with you. New workspaces get seven
card-free days on Basic, and when the clock runs out recording pauses —
reading and export never do, because pausing new work is commerce and
blocking access to what someone already recorded would be extortion.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.billing import entitlements
from apps.billing.models import Plan, Subscription, SubscriptionStatus
from apps.billing.plan_catalogue import LIVE_TIERS, TRIAL_DAYS, PlanFeature, features_for
from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind
from apps.tenancy import services as tenancy_services
from tests.factories import UserFactory
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


# ------------------------------------------------------------- the catalogue
def test_the_live_catalogue_is_exactly_basic_and_plus():
    assert LIVE_TIERS == ("basic", "plus")


def test_basic_keeps_the_books_and_nothing_smart():
    """The user-facing promise, as a set: income and expenses with manual
    planning — no smart features, no investments, no debt."""
    basic = features_for("basic")
    for excluded in (
        PlanFeature.INVESTMENTS,
        PlanFeature.DEBT_PLANNER,
        PlanFeature.SMART_PLANNING,
        PlanFeature.AI_INSIGHTS,
        PlanFeature.AI_COACH,
        PlanFeature.CASHFLOW_FORECAST,
        PlanFeature.AUTOMATION_RULES,
        PlanFeature.ADVANCED_REPORTS,
    ):
        assert excluded not in basic, f"basic must not include {excluded}"
    for included in (PlanFeature.BUDGETS, PlanFeature.BILLS, PlanFeature.RECURRING, PlanFeature.GOALS):
        assert included in basic


def test_plus_has_every_basic_feature_and_the_smart_layer():
    basic, plus = features_for("basic"), features_for("plus")
    assert basic < plus
    for feature in (
        PlanFeature.INVESTMENTS,
        PlanFeature.DEBT_PLANNER,
        PlanFeature.SMART_PLANNING,
        PlanFeature.CASHFLOW_FORECAST,
        PlanFeature.AI_INSIGHTS,
    ):
        assert feature in plus


def test_seed_plans_offers_the_live_tiers_and_retires_the_rest():
    call_command("seed_plans")
    active_tiers = set(Plan.objects.filter(is_active=True).values_list("tier", flat=True))
    assert active_tiers == set(LIVE_TIERS)


# ---------------------------------------------------------------- the trial
def _new_workspace():
    call_command("seed_plans")
    owner = UserFactory()
    return tenancy_services.create_workspace(name="Fresh", owner=owner), owner


def test_a_new_workspace_starts_on_a_card_free_basic_trial():
    tenant, _ = _new_workspace()
    sub = Subscription.objects.get(tenant_id=tenant.id)

    assert sub.status == SubscriptionStatus.TRIALING
    assert sub.plan.tier == "basic"
    assert sub.trial_end is not None
    days = (sub.trial_end - timezone.now()).days
    assert days in (TRIAL_DAYS - 1, TRIAL_DAYS)
    # Card-free is the point: nothing about payment exists yet.
    assert sub.provider == ""


def test_a_trialing_workspace_has_exactly_basics_features():
    tenant, _ = _new_workspace()
    ent = entitlements.resolve_entitlements(tenant_id=tenant.id)

    assert ent.metered is True
    assert "budgets" in ent.features
    assert "investments" not in ent.features


def test_the_trial_clock_is_authoritative_not_the_status_field():
    """Correctness must not depend on a scheduled job having flipped the
    status: a TRIALING row past its trial_end is lapsed, full stop."""
    tenant, _ = _new_workspace()
    Subscription.objects.filter(tenant_id=tenant.id).update(trial_end=timezone.now() - timedelta(hours=1))

    ent = entitlements.resolve_entitlements(tenant_id=tenant.id)
    assert ent.tier == "lapsed"
    assert ent.features == frozenset()


def test_a_lapsed_workspace_cannot_record_but_the_error_promises_export():
    tenant, _ = _new_workspace()
    with tenant_scope(tenant.id):
        account = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        category = finance_services.create_category(
            name="Trial groceries", kind=CategoryKind.EXPENSE, currency="USD"
        )
    Subscription.objects.filter(tenant_id=tenant.id).update(trial_end=timezone.now() - timedelta(hours=1))

    with tenant_scope(tenant.id), pytest.raises(entitlements.PlanLimitExceeded) as excinfo:
        finance_services.record_expense(
            financial_account=account,
            category=category,
            amount_minor=1_000,
            occurred_at=timezone.now(),
        )
    assert "exportable" in str(excinfo.value)


def test_a_workspace_that_never_had_billing_stays_unmetered():
    """Legacy installs (no subscription row) keep full access — the catalogue
    gates its customers, not self-hosted deployments."""
    tenant = uuid.uuid4()
    ent = entitlements.resolve_entitlements(tenant_id=tenant)
    assert ent.metered is False

    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        category = finance_services.create_category(
            name="Groceries", kind=CategoryKind.EXPENSE, currency="USD"
        )
        txn = finance_services.record_expense(
            financial_account=account,
            category=category,
            amount_minor=1_000,
            occurred_at=timezone.now(),
        )
    assert txn is not None


def test_a_second_workspace_creation_never_restarts_a_trial():
    from apps.billing.services import start_trial

    tenant, _ = _new_workspace()
    Subscription.objects.filter(tenant_id=tenant.id).update(trial_end=timezone.now() - timedelta(days=30))
    assert start_trial(tenant_id=tenant.id) is None


# ------------------------------------------------------------ the 402 wall
def test_basic_gets_402_on_investments_with_an_upgrade_message(tenant_context):
    membership, client = tenant_context
    call_command("seed_plans")
    from apps.billing.services import start_trial

    start_trial(tenant_id=membership.tenant_id)

    resp = client.get("/api/v1/investments/portfolio/")
    assert resp.status_code == 402
    assert "Plus" in str(resp.data)


def test_basic_still_reaches_its_own_features(tenant_context):
    membership, client = tenant_context
    call_command("seed_plans")
    from apps.billing.services import start_trial

    start_trial(tenant_id=membership.tenant_id)

    assert client.get("/api/v1/budgeting/budgets/").status_code == 200


def test_lapsed_gets_the_trial_ended_message_not_an_upsell(tenant_context):
    """ "Upgrade to Plus" to someone whose trial ended is the wrong sentence —
    they have no plan at all, and the message must say so."""
    membership, client = tenant_context
    call_command("seed_plans")
    from apps.billing.services import start_trial

    start_trial(tenant_id=membership.tenant_id)
    Subscription.objects.filter(tenant_id=membership.tenant_id).update(
        trial_end=timezone.now() - timedelta(hours=1)
    )

    resp = client.get("/api/v1/investments/portfolio/")
    assert resp.status_code == 402
    assert "trial has ended" in str(resp.data)
