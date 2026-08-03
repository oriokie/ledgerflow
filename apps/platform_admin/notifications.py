"""Platform-side operational alerts.

Mirrors the shape of `apps.notifications.services.raise_notification` so the
two feel like one idea applied twice, but stays a separate function because
the customer notification model is tenant-scoped and RLS-protected. Making
that table nullable-tenant to accommodate platform alerts would open a hole in
the isolation guarantee it exists to enforce.

Every raise is idempotent through `dedupe_key`: a sweep running every five
minutes must produce one "queue is backed up" row, not 288 a day.
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction

from .models import PlatformAlertSeverity, PlatformNotification

logger = logging.getLogger("ledgerflow.platform.notifications")


def raise_platform_alert(
    *,
    category: str,
    title: str,
    severity: str = PlatformAlertSeverity.INFO,
    body: str = "",
    tenant_id=None,
    subject_type: str = "",
    subject_id=None,
    data: dict | None = None,
    dedupe_key: str = "",
) -> PlatformNotification | None:
    """Create an alert, or return the existing one for the same dedupe key.

    Returns None only when a concurrent writer won the race — the alert exists
    either way, which is what the caller actually cares about.
    """
    if dedupe_key:
        existing = PlatformNotification.objects.filter(dedupe_key=dedupe_key).first()
        if existing is not None:
            return existing

    try:
        with transaction.atomic():
            return PlatformNotification.objects.create(
                category=category,
                severity=severity,
                title=title[:200],
                body=body[:600],
                tenant_id=tenant_id,
                subject_type=subject_type,
                subject_id=subject_id,
                data=data or {},
                dedupe_key=dedupe_key,
            )
    except IntegrityError:
        # Another worker inserted the same dedupe key between our check and
        # our write. The alert exists; that is the desired end state.
        return PlatformNotification.objects.filter(dedupe_key=dedupe_key).first()


def acknowledge(*, notification: PlatformNotification, user=None) -> PlatformNotification:
    """Mark an alert handled. Idempotent — re-acknowledging keeps the first
    acknowledgement, so the record shows who actually responded."""
    from django.utils import timezone

    if notification.acknowledged_at is not None:
        return notification
    notification.acknowledged_at = timezone.now()
    notification.acknowledged_by = user
    notification.save(update_fields=["acknowledged_at", "acknowledged_by", "updated_at"])
    return notification


def acknowledge_all(*, user=None, category: str = "") -> int:
    from django.utils import timezone

    query = PlatformNotification.objects.filter(acknowledged_at__isnull=True)
    if category:
        query = query.filter(category=category)
    return query.update(acknowledged_at=timezone.now(), acknowledged_by=user)


def open_alerts(*, severity: str = "", limit: int = 100):
    query = PlatformNotification.objects.filter(acknowledged_at__isnull=True)
    if severity:
        query = query.filter(severity=severity)
    return query.order_by("-created_at")[:limit]
