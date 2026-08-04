"""Daily alerts sweep (Celery beat).

Mirrors the recurring-transaction dispatcher's topology exactly: a lightweight
beat entrypoint streams active tenants and fans out one isolated per-tenant
task, so a slow or failing tenant can't hold up the rest and each runs under its
own RLS binding. Per tenant it: marks overdue bills, then raises bill-due and
budget-threshold notifications. All producers are idempotent (dedupe keys), so a
retry never duplicates an alert.

Notifications are raised workspace-wide (user=None) here rather than to a
specific user, because a beat task has no acting user; per-user targeting/
preferences apply when an alert originates from a user's own action (e.g. the
large-transaction alert in the transaction pipeline).
"""

from __future__ import annotations

import logging
import uuid

from celery import shared_task
from django.db import transaction

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from apps.tenancy.models import Tenant

logger = logging.getLogger("ledgerflow.notifications")

DISPATCH_BATCH = 500


@shared_task(name="notifications.dispatch_alert_sweep")
def dispatch_alert_sweep() -> int:
    """Beat entrypoint: fan out the per-tenant alert sweep across active
    tenants, streamed with a server-side cursor and bounded batches."""
    batch: list[str] = []
    total = 0
    qs = Tenant.objects.filter(is_active=True).values_list("id", flat=True)
    for tenant_id in qs.iterator(chunk_size=DISPATCH_BATCH):
        batch.append(str(tenant_id))
        total += 1
        if len(batch) >= DISPATCH_BATCH:
            dispatch_alert_batch.delay(batch)
            batch = []
    if batch:
        dispatch_alert_batch.delay(batch)
    logger.info("alert-sweep: streamed %d tenants", total)
    return total


@shared_task(name="notifications.dispatch_alert_batch")
def dispatch_alert_batch(tenant_ids: list[str]) -> int:
    for tenant_id in tenant_ids:
        run_alert_sweep_for_tenant.delay(tenant_id)
    return len(tenant_ids)


@shared_task(
    name="notifications.run_alert_sweep_for_tenant",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def run_alert_sweep_for_tenant(self, tenant_id: str) -> int:
    from apps.finance.bills import mark_overdue

    from . import services

    tenant_uuid = uuid.UUID(str(tenant_id))
    try:
        with transaction.atomic():
            bind_db_tenant(tenant_uuid)
            with use_tenant(tenant_uuid):
                mark_overdue()
                bill_alerts = services.evaluate_bill_alerts(within_days=7)
                budget_alerts = services.evaluate_budget_alerts()
        count = len(bill_alerts) + len(budget_alerts)
        logger.info("alert-sweep: tenant %s raised %d notifications", tenant_uuid, count)
        return count
    except Exception as exc:
        logger.exception("alert sweep failed for tenant %s", tenant_id)
        raise self.retry(exc=exc) from exc


@shared_task(
    name="notifications.send_push_notification",
    bind=True,
    max_retries=2,
    default_retry_delay=15,
    acks_late=True,
)
def send_push_notification(self, notification_id: str) -> int:
    """Async wrapper around `push.push_notification`.

    Kept as thin as the debt and receipt task wrappers: the tenant isn't known
    until the row is read, so this binds to itself rather than being called
    with a tenant argument, then delegates to a synchronous, directly-testable
    function.
    """
    import uuid as _uuid

    from .models import Notification
    from .push import push_notification

    try:
        nid = _uuid.UUID(str(notification_id))
        notification = Notification.unscoped.filter(id=nid).first()
        if notification is None:
            return 0
        bind_db_tenant(notification.tenant_id)
        with use_tenant(notification.tenant_id):
            notification = Notification.objects.get(id=nid)
            return push_notification(notification)
    except Exception as exc:
        logger.exception("push dispatch failed for notification %s", notification_id)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=120, name="notifications.send_email")
def send_notification_email_task(self, *, notification_id: str, tenant_id: str) -> dict:
    """Deliver one notification by email.

    The tenant is bound first: both `Notification` and `NotificationPreference`
    are tenant-scoped, so without it the worker cannot read the row it was
    handed — and RLS would return nothing rather than erroring loudly.

    A missing notification is not retried; it was purged or its transaction
    rolled back, and retrying cannot conjure it. Delivery failures are retried,
    since a briefly unreachable mail provider is ordinary rather than a data
    error.
    """
    from .email_channel import send_notification_email
    from .models import Notification

    tenant_uuid = uuid.UUID(str(tenant_id))
    with transaction.atomic():
        bind_db_tenant(tenant_uuid)
        with use_tenant(tenant_uuid):
            notification = Notification.objects.filter(id=notification_id).select_related("user").first()
            if notification is None:
                return {"sent": False, "reason": "notification_missing"}
            try:
                sent = send_notification_email(notification=notification)
            except Exception as exc:  # noqa: BLE001
                raise self.retry(exc=exc) from exc
    return {"sent": sent}


@shared_task(name="notifications.send_monthly_summaries")
def send_monthly_summaries() -> dict:
    """Email each opted-in user a summary of the month just ended.

    This is the mechanism that brings people back. Every figure in it is
    already computed for the dashboard; what was missing was anything that
    reaches a user who has not opened the app — which, for a monthly review
    habit, is most of them most of the time.
    """
    from apps.tenancy.models import Tenant

    from .summary import send_monthly_summary_for_tenant

    sent = failed = 0
    for tenant_id in Tenant.objects.filter(is_active=True).values_list("id", flat=True):
        try:
            sent += send_monthly_summary_for_tenant(tenant_id=tenant_id)
        except Exception:  # noqa: BLE001 — one bad workspace must not stop the run
            logger.exception("monthly summary failed for tenant %s", tenant_id)
            failed += 1
    return {"sent": sent, "tenants_failed": failed}
