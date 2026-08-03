"""The demo seed command.

Worth testing because a broken seed is discovered at exactly the wrong moment —
when someone is trying to demo or debug the console — and because its
production guard is a real safety control.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.billing.dunning_models import DunningCase
from apps.billing.invoicing_models import Invoice
from apps.billing.models import Plan, Subscription, SubscriptionStatus
from apps.platform_admin import metrics
from apps.platform_admin.models import PlatformStaff
from apps.platform_admin.rbac import PlatformRole
from apps.tenancy.models import Tenant
from apps.users.models import User

pytestmark = pytest.mark.django_db


def seed(**kwargs):
    call_command("seed_platform_demo", verbosity=0, **kwargs)


# ------------------------------------------------------------------ guardrail
def test_refuses_to_run_with_debug_off(settings):
    """Seeding fake customers into production would corrupt every revenue
    figure the console reports."""
    settings.DEBUG = False
    with pytest.raises(CommandError, match="not-production"):
        seed()


def test_the_force_flag_overrides_the_guard(settings):
    settings.DEBUG = False
    seed(force=True, admin_only=True)
    assert PlatformStaff.objects.filter(role=PlatformRole.OWNER).exists()


# ---------------------------------------------------------------------- admin
def test_creates_a_signed_in_able_platform_owner(settings):
    settings.DEBUG = True
    seed(admin_only=True)

    staff = PlatformStaff.objects.get(role=PlatformRole.OWNER)
    assert staff.is_active
    # 2FA is waived by default so the seeded account works immediately; the
    # command says so loudly on stdout.
    assert staff.require_mfa is False
    assert staff.user.check_password("PlatformAdmin!2026")
    assert staff.user.is_verified


def test_the_admin_can_reach_the_console(settings):
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    settings.DEBUG = True
    seed(admin_only=True)
    user = User.objects.get(email="admin@ledgerflow.test")

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    response = client.get("/api/v1/platform/me/")

    assert response.status_code == 200
    assert response.json()["role"] == PlatformRole.OWNER.value


def test_mfa_can_be_required(settings):
    settings.DEBUG = True
    seed(admin_only=True, require_mfa=True)
    assert PlatformStaff.objects.get(role=PlatformRole.OWNER).require_mfa is True


def test_a_custom_email_and_password_are_honoured(settings):
    settings.DEBUG = True
    seed(admin_only=True, email="ops@acme.test", password="a-different-password")

    staff = PlatformStaff.objects.get(role=PlatformRole.OWNER)
    assert staff.user.email == "ops@acme.test"
    assert staff.user.check_password("a-different-password")


def test_rerunning_resets_the_password_rather_than_failing(settings):
    """A forgotten seed password from a previous run helps nobody."""
    settings.DEBUG = True
    seed(admin_only=True)
    seed(admin_only=True, password="rotated-password")

    staff = PlatformStaff.objects.get(role=PlatformRole.OWNER)
    assert staff.user.check_password("rotated-password")
    assert PlatformStaff.objects.count() == 1


# ------------------------------------------------------------------ demo data
def test_seeds_a_varied_customer_base(settings):
    settings.DEBUG = True
    seed()

    assert Tenant.objects.count() == 10
    # Each screen needs something to render: an expiring trial, a past-due
    # account in recovery, a suspended workspace, an overdue invoice.
    assert Subscription.objects.filter(status=SubscriptionStatus.TRIALING).exists()
    assert Tenant.objects.filter(is_active=False).exists()
    assert DunningCase.objects.exists()
    assert Invoice.objects.filter(status="overdue").exists()
    assert Invoice.objects.filter(status="paid").exists()


def test_the_seeded_dashboard_reports_meaningful_numbers(settings):
    settings.DEBUG = True
    seed()
    data = metrics.dashboard.uncached(currency="USD")

    assert data["revenue"]["mrr_minor"] > 0
    assert data["revenue"]["paying_customers"] > 0
    # A churn rate of exactly 1.0 means the denominator collapsed — the seed
    # backdates subscriptions specifically so this reads plausibly.
    assert 0 < data["churn"]["rate"] < 1
    assert data["payments"]["success_rate"] not in (None, 0)
    assert data["trials"]["conversion_rate"] is not None


def test_annual_plans_are_normalised_in_the_seeded_mrr(settings):
    settings.DEBUG = True
    seed()

    annual = Plan.objects.get(interval="yearly", currency="USD")
    buckets = {b["key"]: b["mrr_minor"] for b in metrics.revenue_by("plan", currency="USD")}
    assert buckets[annual.name] == round(annual.price_minor / 12)


def test_the_seed_never_binds_a_tenant_context(settings, monkeypatch):
    """The seed creates control-plane data only — which is all the platform
    console can read anyway.

    Asserting "no ledger rows exist" would be vacuous: reading a tenant-scoped
    table without a bound tenant either raises `UnscopedAccessError` (app
    layer) or returns zero rows by RLS policy (database layer), so the count is
    zero whether or not the seed wrote anything. The meaningful assertion is
    that the command never binds a tenant at all — without that, it has no way
    to write a household's financial data even by accident.
    """
    from apps.common import rls

    bound: list = []
    real = rls.bind_db_tenant
    monkeypatch.setattr(rls, "bind_db_tenant", lambda tid: bound.append(tid) or real(tid))

    settings.DEBUG = True
    seed()

    assert bound == []


def test_seeding_twice_does_not_duplicate_customers(settings):
    settings.DEBUG = True
    seed()
    before = Tenant.objects.count()
    seed()

    assert Tenant.objects.count() == before
    assert Subscription.objects.count() == Subscription.objects.values("tenant_id").distinct().count()


def test_revenue_is_spread_across_months(settings):
    """A single spike in the current month makes the trend chart useless."""
    settings.DEBUG = True
    seed()

    series = metrics.monthly_revenue_series(months=6, currency="USD")
    months_with_revenue = [row for row in series if row["net_minor"] > 0]
    assert len(months_with_revenue) >= 2
