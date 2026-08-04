"""Operational health probes.

Every probe is defensive to the point of never raising. A health dashboard
that 500s when Redis is down has failed at the one moment it was needed — the
correct output is a red panel saying "Redis unreachable", not an error page.
So each probe catches broadly and returns a status string.

Statuses are a small closed vocabulary:
    ok        working normally
    degraded  working, but outside its healthy threshold
    down      not reachable
    unknown   not configured, or could not be determined

`unknown` is distinct from `down` on purpose. An unconfigured SMS provider is
not an outage, and colouring it red trains operators to ignore red.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

logger = logging.getLogger("ledgerflow.platform.health")

OK, DEGRADED, DOWN, UNKNOWN = "ok", "degraded", "down", "unknown"

#: Queue depth above which the worker pool is considered to be falling behind.
QUEUE_BACKLOG_THRESHOLD = int(getattr(settings, "PLATFORM_QUEUE_BACKLOG_THRESHOLD", 500))
#: Share of webhook events left unprocessed before the integration is degraded.
WEBHOOK_FAILURE_THRESHOLD = 0.1


def _probe(name: str, fn) -> dict:
    """Run one probe, timing it and swallowing any failure."""
    started = time.monotonic()
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 — a probe must never propagate
        logger.warning("health probe %s failed: %s", name, exc)
        result = {"status": DOWN, "detail": str(exc)[:200]}
    result.setdefault("status", UNKNOWN)
    result["name"] = name
    result["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
    return result


# ---------------------------------------------------------------- datastores
def database() -> dict:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
        size_bytes = None
        connections = None
        if connection.vendor == "postgresql":
            cursor.execute("SELECT pg_database_size(current_database())")
            size_bytes = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
            connections = cursor.fetchone()[0]
    return {
        "status": OK,
        "vendor": connection.vendor,
        "size_bytes": size_bytes,
        "connections": connections,
    }


def cache_backend() -> dict:
    probe_key = "platform:health:probe"
    cache.set(probe_key, "1", 10)
    if cache.get(probe_key) != "1":
        # A cache that accepts writes and returns nothing is worse than one
        # that is plainly down — it silently halves throughput.
        return {"status": DEGRADED, "detail": "Cache accepted a write but did not return it."}
    cache.delete(probe_key)
    return {"status": OK, "backend": settings.CACHES["default"]["BACKEND"].rsplit(".", 1)[-1]}


def queues() -> dict:
    """Broker depth and worker liveness via the Celery control API.

    `inspect()` talks to live workers over the broker and blocks if none reply,
    so it is called with a short timeout. No workers is `down` rather than an
    error: it is a real, actionable state, and the most likely one during an
    incident.
    """
    from config.celery import app as celery_app

    inspector = celery_app.control.inspect(timeout=1.0)
    active = inspector.active() or {}
    reserved = inspector.reserved() or {}
    scheduled = inspector.scheduled() or {}

    workers = sorted(set(active) | set(reserved) | set(scheduled))
    if not workers:
        return {
            "status": DOWN,
            "workers": 0,
            "detail": "No Celery workers responded.",
            "active": 0,
            "reserved": 0,
            "scheduled": 0,
        }

    active_count = sum(len(v) for v in active.values())
    reserved_count = sum(len(v) for v in reserved.values())
    backlog = active_count + reserved_count

    return {
        "status": DEGRADED if backlog > QUEUE_BACKLOG_THRESHOLD else OK,
        "workers": len(workers),
        "worker_names": workers,
        "active": active_count,
        "reserved": reserved_count,
        "scheduled": sum(len(v) for v in scheduled.values()),
        "backlog": backlog,
        "threshold": QUEUE_BACKLOG_THRESHOLD,
    }


def storage() -> dict:
    backend = settings.STORAGES["default"]["BACKEND"]
    remote = "S3" in backend or "boto" in backend.lower()
    return {
        "status": OK,
        "backend": backend.rsplit(".", 1)[-1],
        "remote": remote,
        "bucket": getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or None,
    }


def outbox() -> dict:
    """Undelivered event backlog — the relay's own health."""
    from apps.common.outbox import OutboxEvent

    pending = OutboxEvent.objects.filter(published_at__isnull=True).count()
    oldest = (
        OutboxEvent.objects.filter(published_at__isnull=True)
        .order_by("created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    stale = bool(oldest and (timezone.now() - oldest) > timedelta(minutes=15))
    return {
        "status": DEGRADED if (pending > QUEUE_BACKLOG_THRESHOLD or stale) else OK,
        "pending": pending,
        "oldest_pending_at": oldest,
    }


# -------------------------------------------------------------- integrations
def _configured(*values) -> bool:
    return all(bool(getattr(settings, name, "")) for name in values)


def payment_providers() -> list[dict]:
    """Configuration and recent delivery health per payment provider."""
    from apps.billing.models import WebhookEvent

    since = timezone.now() - timedelta(days=1)
    results = []
    for key, required in (
        ("stripe", ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET")),
        ("mpesa", ("MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET", "MPESA_SHORTCODE")),
    ):
        events = WebhookEvent.objects.filter(provider=key, created_at__gte=since)
        total = events.count()
        failed = events.filter(processed_at__isnull=True).exclude(error="").count()

        if not _configured(*required):
            status = UNKNOWN  # sandbox mode is a valid state, not an outage
        elif total and failed / total > WEBHOOK_FAILURE_THRESHOLD:
            status = DEGRADED
        else:
            status = OK

        results.append(
            {
                "name": key,
                "status": status,
                "configured": _configured(*required),
                "webhooks_24h": total,
                "webhooks_failed_24h": failed,
            }
        )
    return results


def integrations() -> list[dict]:
    email_configured = bool(getattr(settings, "EMAIL_HOST", "")) and "smtp" in getattr(
        settings, "EMAIL_BACKEND", ""
    )
    push_configured = bool(getattr(settings, "VAPID_PRIVATE_KEY", "")) and bool(
        getattr(settings, "VAPID_PUBLIC_KEY", "")
    )
    llm_configured = bool(getattr(settings, "LLM_ENABLED", False))

    return [
        *payment_providers(),
        {"name": "email", "status": OK if email_configured else UNKNOWN, "configured": email_configured},
        {"name": "web_push", "status": OK if push_configured else UNKNOWN, "configured": push_configured},
        {"name": "llm", "status": OK if llm_configured else UNKNOWN, "configured": llm_configured},
    ]


# -------------------------------------------------------------------- alerts
def alerts() -> list[dict]:
    """Things an operator should look at right now.

    Derived live rather than read from the notification table so the panel is
    correct even if the alert-raising sweep is itself broken — which is exactly
    the failure mode where a health dashboard has to keep working.
    """
    from apps.billing.dunning_models import DunningCase, DunningCaseStatus
    from apps.billing.models import Payment, PaymentStatus, WebhookEvent
    from apps.common.outbox import OutboxEvent

    day_ago = timezone.now() - timedelta(days=1)
    found: list[dict] = []

    failed_payments = Payment.objects.filter(status=PaymentStatus.FAILED, created_at__gte=day_ago).count()
    if failed_payments:
        found.append(
            {
                "severity": "warning" if failed_payments < 10 else "critical",
                "category": "payment.failed",
                "message": f"{failed_payments} payment(s) failed in the last 24 hours.",
                "count": failed_payments,
            }
        )

    failed_webhooks = (
        WebhookEvent.objects.filter(processed_at__isnull=True, created_at__gte=day_ago)
        .exclude(error="")
        .count()
    )
    if failed_webhooks:
        found.append(
            {
                "severity": "critical",
                "category": "webhook.failed",
                "message": f"{failed_webhooks} webhook(s) failed to process in the last 24 hours.",
                "count": failed_webhooks,
            }
        )

    open_dunning = DunningCase.objects.filter(status=DunningCaseStatus.OPEN).count()
    if open_dunning:
        found.append(
            {
                "severity": "info",
                "category": "dunning.open",
                "message": f"{open_dunning} account(s) in payment recovery.",
                "count": open_dunning,
            }
        )

    pending_events = OutboxEvent.objects.filter(published_at__isnull=True).count()
    if pending_events > QUEUE_BACKLOG_THRESHOLD:
        found.append(
            {
                "severity": "critical",
                "category": "queue.backlog",
                "message": f"{pending_events} events awaiting delivery.",
                "count": pending_events,
            }
        )

    return found


# ------------------------------------------------------------------ rollup
def overall(components: list[dict]) -> str:
    """Worst component wins. `unknown` never degrades the rollup — an
    unconfigured optional integration is not an incident."""
    statuses = {c.get("status") for c in components}
    if DOWN in statuses:
        return DOWN
    if DEGRADED in statuses:
        return DEGRADED
    return OK


def snapshot() -> dict:
    """The whole health picture. Never raises."""
    components = [
        _probe("database", database),
        _probe("cache", cache_backend),
        _probe("queues", queues),
        _probe("storage", storage),
        _probe("outbox", outbox),
    ]
    try:
        integration_rows = integrations()
    except Exception as exc:  # noqa: BLE001
        logger.warning("integration probe failed: %s", exc)
        integration_rows = []
    try:
        alert_rows = alerts()
    except Exception as exc:  # noqa: BLE001
        logger.warning("alert probe failed: %s", exc)
        alert_rows = []

    return {
        "generated_at": timezone.now(),
        "status": overall(components),
        "components": components,
        "integrations": integration_rows,
        "alerts": alert_rows,
    }
