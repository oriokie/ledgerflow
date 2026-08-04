"""Scheduled platform work.

Each task is thin: it calls a service and reports a summary. Business logic
stays in the service layer so the same operation is testable synchronously and
produces identical audit rows whether a beat schedule or an operator triggered
it.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("ledgerflow.platform.tasks")


@shared_task(name="platform.run_dunning")
def run_dunning() -> dict:
    """Execute every dunning attempt that has come due."""
    from apps.billing.dunning import run_due_attempts

    summary = run_due_attempts()
    logger.info("dunning sweep: %s", summary)
    return summary


@shared_task(name="platform.mark_overdue_invoices")
def mark_overdue_invoices() -> dict:
    from apps.billing.invoicing import mark_overdue

    moved = mark_overdue()
    return {"marked_overdue": moved}


@shared_task(name="platform.expire_impersonations")
def expire_impersonations() -> dict:
    """Close elapsed impersonation grants.

    Belt-and-braces: `resolve()` already expires a grant lazily on use, but a
    session that is simply abandoned would otherwise read "active" in the
    console forever.
    """
    from apps.platform_admin.services.impersonation import expire_stale

    return {"expired": expire_stale()}


@shared_task(name="platform.capture_usage_snapshots")
def capture_usage_snapshots(limit: int = 500) -> dict:
    """Aggregate per-tenant usage across the RLS boundary.

    The platform console cannot read tenant-scoped tables, and should not be
    able to. This task binds each tenant's own context in turn — exactly as a
    member's request would — and copies out counts and byte totals only. No
    financial content crosses the boundary; only magnitudes do.
    """
    from django.db import transaction
    from django.db.models import Sum

    from apps.common.rls import bind_db_tenant
    from apps.common.tenant_context import use_tenant
    from apps.platform_admin.models import TenantUsageSnapshot
    from apps.tenancy.models import Tenant

    captured_at = timezone.now().replace(microsecond=0)
    written = 0

    for (tenant_id,) in Tenant.objects.values_list("id")[:limit]:
        try:
            with transaction.atomic():
                bind_db_tenant(tenant_id)
                with use_tenant(tenant_id):
                    from apps.finance.models import Attachment, FinancialAccount, Transaction

                    accounts = FinancialAccount.objects.count()
                    transactions = Transaction.objects.count()
                    attachment_count = Attachment.objects.count()
                    storage_bytes = Attachment.objects.aggregate(total=Sum("byte_size"))["total"] or 0

            from apps.tenancy.models import Membership

            TenantUsageSnapshot.objects.update_or_create(
                tenant_id=tenant_id,
                captured_at=captured_at,
                defaults={
                    "member_count": Membership.objects.filter(tenant_id=tenant_id).count(),
                    "account_count": accounts,
                    "transaction_count": transactions,
                    "attachment_count": attachment_count,
                    "storage_bytes": storage_bytes,
                },
            )
            written += 1
        except Exception:  # noqa: BLE001 — one bad tenant must not stop the sweep
            logger.exception("usage snapshot failed for tenant %s", tenant_id)

    return {"snapshots_written": written, "captured_at": captured_at.isoformat()}


@shared_task(name="platform.sweep_alerts")
def sweep_alerts() -> dict:
    """Turn live health signals into acknowledgeable platform notifications."""
    from apps.platform_admin.health import alerts
    from apps.platform_admin.notifications import raise_platform_alert

    raised = 0
    today = timezone.now().date().isoformat()
    for alert in alerts():
        result = raise_platform_alert(
            category=alert["category"],
            severity=alert["severity"],
            title=alert["message"],
            # One row per category per day: an operator wants to know the
            # queue is backed up, not to be told 288 times.
            dedupe_key=f"{alert['category']}:{today}",
            data={"count": alert.get("count")},
        )
        if result is not None:
            raised += 1
    return {"alerts_raised": raised}
