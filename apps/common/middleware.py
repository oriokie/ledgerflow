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


class NoStoreAPIMiddleware:
    """Forbid every cache from storing an API response.

    Without this the API sends no cache directives at all, which does not mean
    "don't cache" — it means "decide for yourself". A shared cache is then free
    to store a 200 keyed on the URL alone and replay it: a CDN, a corporate
    proxy, or (as found in production) Apache's mod_cache on a shared host. The
    observed symptom was a workspace list frozen at its first, empty response
    while the account had nine; the *unobserved* one is worse, because a stored
    response carrying one account's financial data can be served to a different
    visitor entirely. Bearer auth doesn't protect against that — the cache
    never sees the Authorization header, only the path.

    Set rather than negotiated: nothing under /api/ is publicly cacheable, so
    the safe default is no-store everywhere, and a view that genuinely wants
    caching (a public FX rate, say) opts out by setting the header itself.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            # setdefault, not assignment: a view that already made a deliberate
            # decision about its own cacheability keeps it.
            response.setdefault("Cache-Control", "no-store, private")
        return response
