"""Outbox relay: publishes committed domain events to downstream consumers
(audit, notifications, insights projections). Runs on a short Celery beat
schedule. At-least-once delivery; consumers must be idempotent (dedup on the
immutable event_id).
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .outbox import OutboxEvent
from .publishing import get_publisher

logger = logging.getLogger("ledgerflow.events")

BATCH = 500


@shared_task
def relay_outbox() -> int:
    """Publish unpublished events in id order. An event is marked published ONLY
    after the publisher confirms delivery; a failure stops the batch (to
    preserve per-aggregate ordering) and leaves the rest for the next tick.

    Each event is marked in its own transaction so a mid-batch crash never loses
    a delivered event's published mark.
    """
    publisher = get_publisher()
    pending = list(OutboxEvent.objects.filter(published_at__isnull=True).order_by("id")[:BATCH])
    published = 0
    for event in pending:
        try:
            publisher.publish(event)
        except Exception:
            logger.exception(
                "outbox publish failed; stopping batch to preserve order",
                extra={"event_id": str(event.event_id), "event_type": event.event_type},
            )
            break
        with transaction.atomic():
            OutboxEvent.objects.filter(pk=event.pk, published_at__isnull=True).update(
                published_at=timezone.now()
            )
        published += 1
    return published
