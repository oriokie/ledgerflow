"""Structured logging: every log line is correlated to the request that
produced it via a request ID (accepted from `X-Request-ID` or generated),
propagated through contextvars so it reaches Celery tasks spawned from a
request too.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(value: str) -> None:
    _request_id.set(value)


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class JSONFormatter(logging.Formatter):
    """One-line JSON per record — safe for log aggregators (Datadog, CloudWatch, ELK)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key in ("tenant_id", "user_id", "duration_ms", "status_code", "method", "path"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, default=str)
