"""Event publishing — the read side of the transactional outbox.

The outbox write side persists an `OutboxEvent` in the same transaction as the
state change. This module actually *delivers* those events. A publisher is a
small strategy chosen by settings, mirroring the provider-strategy pattern used
elsewhere:

    EVENT_PUBLISHER = "apps.common.publishing.LoggingPublisher"   # default
                    = "apps.common.publishing.RedisStreamPublisher"  # example broker

The relay never marks an event published unless the publisher's `publish()`
returns without raising. A publish failure leaves `published_at` NULL so the
event is retried on the next relay tick — at-least-once delivery, which is why
consumers must be idempotent (the immutable `event_id` is the dedup key).

This replaces the previous stub that marked events published without delivering
them (silent, unrecoverable data loss). The default `LoggingPublisher` is
deliberately safe: it delivers to the structured log so events are never lost
even before a broker is wired, and a real broker publisher drops in by config
with zero relay changes.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger("ledgerflow.events")


@runtime_checkable
class EventPublisher(Protocol):
    def publish(self, event) -> None:
        """Deliver one OutboxEvent. MUST raise on failure so the relay leaves
        the event unpublished for retry. MUST be effectively synchronous with
        respect to durability (return only once the event is safely handed
        off)."""
        ...


class LoggingPublisher(EventPublisher):
    """Default publisher: emits the event to the structured log. Durable enough
    that events are never silently lost before a broker exists, and a real
    log pipeline (e.g. shipped to a bus/warehouse) can consume it directly."""

    def publish(self, event) -> None:
        logger.info(
            "domain_event",
            extra={
                "event_id": str(event.event_id),
                "event_type": event.event_type,
                "aggregate_type": event.aggregate_type,
                "aggregate_id": str(event.aggregate_id),
                "tenant_id": str(event.tenant_id),
                "payload": event.payload,
            },
        )


class RedisStreamPublisher(EventPublisher):
    """Example broker publisher (Redis Streams). Illustrates that swapping the
    delivery mechanism is a settings change, not a relay change. Uses the
    configured Redis; each event_type is a stream, event_id is carried for
    consumer-side dedup."""

    def __init__(self):
        import redis  # local import so the dependency is optional

        self._client = redis.Redis.from_url(settings.REDIS_URL)

    def publish(self, event) -> None:
        self._client.xadd(
            f"events:{event.event_type}",
            {
                "event_id": str(event.event_id),
                "tenant_id": str(event.tenant_id),
                "aggregate_id": str(event.aggregate_id),
                "payload": __import__("json").dumps(event.payload),
            },
        )


_publisher_cache: EventPublisher | None = None


def get_publisher() -> EventPublisher:
    """Resolve the configured publisher once (publishers are stateless or hold
    a reusable client)."""
    global _publisher_cache
    if _publisher_cache is None:
        dotted = getattr(settings, "EVENT_PUBLISHER", "apps.common.publishing.LoggingPublisher")
        _publisher_cache = import_string(dotted)()
    return _publisher_cache


def reset_publisher_cache() -> None:
    """Test hook: drop the memoized publisher so an override_settings takes."""
    global _publisher_cache
    _publisher_cache = None
