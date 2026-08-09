"""apps.billing.management.commands.backfill_trial_subscriptions.

`tenancy.create_workspace` calls `billing.start_trial` best-effort: if it
fails (most commonly because the plan catalogue hasn't been seeded yet), the
workspace is created anyway with no Subscription row, and the failure is only
ever logged. That tenant is stuck legacy-unmetered until something retries
`start_trial` for it — these tests model that exact gap and prove the backfill
command closes it without disturbing tenants that already have a subscription.
"""

from __future__ import annotations

import io

import pytest
from django.core.management import call_command

from apps.billing.models import Subscription, SubscriptionStatus
from apps.tenancy import services as tenancy_services
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _unseeded_workspace(name="Fresh"):
    """A tenant created before the plan catalogue existed: create_workspace's
    best-effort start_trial call finds no Basic plan, logs a warning, and
    leaves the workspace with no Subscription row — exactly the production
    gap this command exists to close."""
    owner = UserFactory()
    return tenancy_services.create_workspace(name=name, owner=owner)


def _run(*args):
    out = io.StringIO()
    call_command("backfill_trial_subscriptions", *args, stdout=out)
    return out.getvalue()


def test_backfills_a_tenant_created_before_the_catalogue_was_seeded():
    tenant = _unseeded_workspace()
    assert not Subscription.objects.filter(tenant_id=tenant.id).exists()

    call_command("seed_plans")
    output = _run()

    sub = Subscription.objects.get(tenant_id=tenant.id)
    assert sub.status == SubscriptionStatus.TRIALING
    assert sub.plan.tier == "basic"
    assert str(tenant.id) in output
    assert "1 started, 0 skipped" in output


def test_dry_run_reports_without_writing():
    tenant = _unseeded_workspace()
    call_command("seed_plans")

    output = _run("--dry-run")

    assert not Subscription.objects.filter(tenant_id=tenant.id).exists()
    assert str(tenant.id) in output
    assert "Dry run" in output


def test_never_touches_a_tenant_that_already_has_a_subscription():
    call_command("seed_plans")
    tenant = _unseeded_workspace()  # plans exist now, so this one enrolls normally
    original = Subscription.objects.get(tenant_id=tenant.id)

    _run()

    unchanged = Subscription.objects.get(tenant_id=tenant.id)
    assert unchanged.id == original.id
    assert unchanged.trial_end == original.trial_end


def test_reports_skipped_when_the_catalogue_is_still_not_seeded():
    tenant = _unseeded_workspace()

    output = _run()

    assert not Subscription.objects.filter(tenant_id=tenant.id).exists()
    assert "0 started, 1 skipped" in output
    assert "seed_plans" in output


def test_tenant_id_option_limits_the_scan_to_one_tenant():
    target = _unseeded_workspace("Target")
    other = _unseeded_workspace("Other")
    call_command("seed_plans")

    _run("--tenant-id", str(target.id))

    assert Subscription.objects.filter(tenant_id=target.id).exists()
    assert not Subscription.objects.filter(tenant_id=other.id).exists()
