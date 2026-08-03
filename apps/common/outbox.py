"""Transactional outbox.

Services persist domain changes AND an OutboxEvent row in the same DB
transaction. A relay worker (Celery beat -> broker) publishes committed events
to consumers: `audit`, `notifications`, `insights` projections. This avoids the
dual-write problem (DB commit + broker publish can't be atomic otherwise) and
gives us a durable, ordered, replayable event log — which doubles as the
financial audit trail required by the brief.
"""

from __future__ import annotations

import uuid

from django.db import models

from .models import TimeStampedModel


class OutboxEvent(TimeStampedModel):
    id = models.BigAutoField(primary_key=True)  # monotonic => ordered relay
    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    tenant_id = models.UUIDField(db_index=True, editable=False)
    aggregate_type = models.CharField(max_length=64)  # e.g. "ledger.JournalEntry"
    aggregate_id = models.UUIDField()
    event_type = models.CharField(max_length=128)  # e.g. "ledger.journal_entry.posted"
    payload = models.JSONField(default=dict)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["published_at", "id"])]

    def __str__(self) -> str:
        return f"{self.event_type}({self.aggregate_id})"
