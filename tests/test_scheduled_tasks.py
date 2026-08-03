"""Scheduled tasks.

`platform_admin/tasks.py` sat at 0% coverage and `finance/tasks.py` at 64%.
These run unattended against production data with nobody watching, which is the
profile of code that most needs a test and least gets one: a task that silently
does nothing is indistinguishable from a task with nothing to do.

Each test asserts the *effect* the task is supposed to have, not that it ran
without raising — a sweep that returns cleanly having processed zero rows is
the failure mode worth catching.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.billing import dunning
from apps.billing.models import (
    BillingInterval,
    Payment,
    PaymentMethod,
    PaymentMethodKind,
    PaymentStatus,
    Plan,
    PlanTier,
    Subscription,
    SubscriptionStatus,
)
from apps.tenancy.models import Tenant
from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


def _paid_subscription(tenant_id, price=900):
    plan = Plan.objects.create(
        tier=PlanTier.PLUS, name="Plus", price_minor=price, currency="USD",
        interval=BillingInterval.MONTHLY,
    )
    return Subscription.objects.create(
        tenant_id=tenant_id, plan=plan, status=SubscriptionStatus.ACTIVE, provider="stripe"
    )


# ==================================================== platform.run_dunning
def test_dunning_sweep_executes_due_attempts():
    from apps.platform_admin.tasks import run_dunning

    membership = MembershipFactory()
    dunning.ensure_default_policy()
    PaymentMethod.objects.create(
        tenant_id=membership.tenant_id, kind=PaymentMethodKind.CARD, is_default=True,
        provider="stripe", provider_ref="pm_test", brand="visa", last4="4242",
    )
    sub = _paid_subscription(membership.tenant_id)
    case = dunning.open_case(subscription=sub, now=timezone.now() - timedelta(days=2))

    summary = run_dunning()

    assert summary["executed"] > 0, "the sweep found nothing to do"
    case.refresh_from_db()
    assert case.attempts_made > 0 or case.status != "open"


def test_dunning_sweep_is_a_no_op_when_nothing_is_due():
    """Distinguishes 'nothing to do' from 'broken and silent'."""
    from apps.platform_admin.tasks import run_dunning

    assert run_dunning() == {"executed": 0, "succeeded": 0, "failed": 0, "skipped": 0}


# ======================================== platform.mark_overdue_invoices
def test_overdue_sweep_moves_only_past_due_invoices():
    from apps.billing import invoicing
    from apps.billing.invoicing_models import InvoiceStatus
    from apps.platform_admin.tasks import mark_overdue_invoices

    tenant = uuid.uuid4()
    today = timezone.now().date()
    line = [invoicing.LineItemSpec(description="Plus", amount_minor=900)]

    overdue = invoicing.create_invoice(
        tenant_id=tenant, currency="USD", line_items=line,
        issue_date=today - timedelta(days=30), due_date=today - timedelta(days=16),
    )
    invoicing.issue_invoice(invoice=overdue)
    current = invoicing.create_invoice(tenant_id=tenant, currency="USD", line_items=line)
    invoicing.issue_invoice(invoice=current)

    assert mark_overdue_invoices() == {"marked_overdue": 1}
    overdue.refresh_from_db()
    current.refresh_from_db()
    assert overdue.status == InvoiceStatus.OVERDUE
    assert current.status == InvoiceStatus.PENDING


# ==================================== platform.expire_impersonations
def test_stale_impersonation_grants_are_swept():
    """An abandoned session is a live credential until something closes it."""
    from apps.platform_admin.models import ImpersonationGrant, ImpersonationStatus
    from apps.platform_admin.rbac import PlatformRole
    from apps.platform_admin.services import impersonation
    from apps.platform_admin.tasks import expire_impersonations
    from tests.test_platform_admin_rbac import make_staff

    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    membership = MembershipFactory()
    grant, _ = impersonation.start(
        staff=staff, tenant_id=membership.tenant_id,
        reason="Investigating a reported import failure",
    )
    ImpersonationGrant.objects.filter(pk=grant.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )

    assert expire_impersonations() == {"expired": 1}
    grant.refresh_from_db()
    assert grant.status == ImpersonationStatus.EXPIRED


def test_live_impersonation_grants_are_left_alone():
    from apps.platform_admin.models import ImpersonationStatus
    from apps.platform_admin.rbac import PlatformRole
    from apps.platform_admin.services import impersonation
    from apps.platform_admin.tasks import expire_impersonations
    from tests.test_platform_admin_rbac import make_staff

    staff = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    membership = MembershipFactory()
    grant, _ = impersonation.start(
        staff=staff, tenant_id=membership.tenant_id, reason="Reproducing a sync bug"
    )

    assert expire_impersonations() == {"expired": 0}
    grant.refresh_from_db()
    assert grant.status == ImpersonationStatus.ACTIVE


# ==================================== platform.capture_usage_snapshots
def test_usage_snapshots_cross_the_rls_boundary_safely():
    """The task binds each tenant's own context to read counts the console
    cannot. Only magnitudes may cross — never financial content."""
    from apps.platform_admin.models import TenantUsageSnapshot
    from apps.platform_admin.tasks import capture_usage_snapshots

    a = MembershipFactory()
    b = MembershipFactory()

    result = capture_usage_snapshots()

    assert result["snapshots_written"] >= 2
    for membership in (a, b):
        snapshot = TenantUsageSnapshot.objects.filter(tenant_id=membership.tenant_id).first()
        assert snapshot is not None
        assert snapshot.member_count == 1
        # Counts and bytes only — the snapshot carries no transaction detail.
        assert not hasattr(snapshot, "transactions")


def test_one_failing_tenant_does_not_abort_the_whole_sweep():
    """A sweep that stops at the first bad row leaves every later tenant
    unmeasured, and nothing says so."""
    from apps.platform_admin.models import TenantUsageSnapshot
    from apps.platform_admin.tasks import capture_usage_snapshots

    for _ in range(3):
        MembershipFactory()
    # A tenant row with no memberships and no schema objects still counts.
    Tenant.objects.create(name="Orphan", base_currency="USD")

    result = capture_usage_snapshots()
    assert result["snapshots_written"] >= 3
    assert TenantUsageSnapshot.objects.count() >= 3


# ============================================ platform.sweep_alerts
def test_alert_sweep_raises_a_notification_for_failed_payments():
    from apps.platform_admin.models import PlatformNotification
    from apps.platform_admin.tasks import sweep_alerts

    membership = MembershipFactory()
    sub = _paid_subscription(membership.tenant_id)
    Payment.objects.create(
        tenant_id=membership.tenant_id, subscription=sub, amount_minor=900, currency="USD",
        status=PaymentStatus.FAILED, provider="stripe", failure_reason="card_declined",
    )

    result = sweep_alerts()
    assert result["alerts_raised"] >= 1
    assert PlatformNotification.objects.filter(category="payment.failed").exists()


def test_the_alert_sweep_does_not_duplicate_within_a_day():
    """Running every 15 minutes must produce one row, not 96."""
    from apps.platform_admin.models import PlatformNotification
    from apps.platform_admin.tasks import sweep_alerts

    membership = MembershipFactory()
    sub = _paid_subscription(membership.tenant_id)
    Payment.objects.create(
        tenant_id=membership.tenant_id, subscription=sub, amount_minor=900, currency="USD",
        status=PaymentStatus.FAILED, provider="stripe",
    )

    sweep_alerts()
    sweep_alerts()
    sweep_alerts()

    assert PlatformNotification.objects.filter(category="payment.failed").count() == 1


def test_a_quiet_platform_raises_no_alerts():
    from apps.platform_admin.tasks import sweep_alerts

    assert sweep_alerts() == {"alerts_raised": 0}


# ============================== finance.reconcile_account_balances
def test_balance_drift_is_detected_repaired_and_reported():
    """The drift detector is the last line of defence against a write path that
    bypassed the posting service. It was only partly covered."""
    from apps.finance.tasks import reconcile_balances_for_tenant
    from apps.ledger.models import AccountBalance
    from apps.platform_admin.models import PlatformNotification
    from tests.conftest import _bearer_client

    membership = MembershipFactory()
    client = _bearer_client(membership.user, tenant_id=membership.tenant_id)
    account = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Current", "account_type": "checking", "currency": "USD"},
        format="json",
    ).data

    # Corrupt the materialised balance the way a stray write would. Uses the
    # unscoped manager because this is deliberately reaching past the tenant
    # context to simulate a write path that bypassed the posting service.
    from apps.finance.models import FinancialAccount

    financial = FinancialAccount.unscoped.get(id=account["id"])
    updated = AccountBalance.unscoped.filter(
        account_id=financial.ledger_account_id
    ).update(balance_minor=999_999)
    assert updated == 1, "no materialised balance row to corrupt"

    drifted = reconcile_balances_for_tenant(str(membership.tenant_id))

    assert drifted == 1
    balance = AccountBalance.unscoped.get(account_id=financial.ledger_account_id)
    assert balance.balance_minor == 0, "drift was detected but not repaired"
    # Silent repair would hide the bug that caused it.
    assert PlatformNotification.objects.filter(category="ledger.drift").exists()


def test_a_correct_balance_reports_no_drift():
    from apps.finance.tasks import reconcile_balances_for_tenant
    from tests.conftest import _bearer_client

    membership = MembershipFactory()
    client = _bearer_client(membership.user, tenant_id=membership.tenant_id)
    client.post(
        "/api/v1/finance/accounts/",
        {"name": "Current", "account_type": "checking", "currency": "USD"},
        format="json",
    )
    assert reconcile_balances_for_tenant(str(membership.tenant_id)) == 0


# ================================== billing.send_invoice_email (task path)
def test_the_invoice_email_task_is_reachable_from_the_beat_schedule():
    """Every scheduled task name in settings must resolve to a real task —
    a typo in the beat schedule fails silently at runtime."""
    from django.conf import settings

    from config.celery import app

    # Celery discovers task modules lazily, so a bare `app.tasks` in a test
    # process is nearly empty — the check would pass vacuously without this.
    app.loader.import_default_modules()
    registered = set(app.tasks.keys())
    for entry in settings.CELERY_BEAT_SCHEDULE.values():
        assert entry["task"] in registered, f"{entry['task']} is scheduled but not registered"
