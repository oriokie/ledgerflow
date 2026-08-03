"""Cross-cutting HTTP middleware: request correlation and access logging.
These run for every request regardless of DRF/auth, so they sit in Django's
MIDDLEWARE list rather than at the API layer."""

from __future__ import annotations

import logging
import time

from .logging import new_request_id, set_request_id

access_logger = logging.getLogger("ledgerflow.access")


class RequestIDMiddleware:
    """Accepts a client-supplied `X-Request-ID` (useful when a gateway/mobile
    client already generates one) or mints a new one; echoes it back so the
    caller can correlate logs on both sides."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        set_request_id(request_id)
        request.request_id = request_id
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response


class RequestLoggingMiddleware:
    """One structured access-log line per request, with latency and status."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        access_logger.info(
            "%s %s -> %s",
            request.method,
            request.path,
            response.status_code,
            extra={
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "tenant_id": getattr(request, "tenant_id", None),
                "user_id": getattr(getattr(request, "user", None), "id", None),
            },
        )
        return response
