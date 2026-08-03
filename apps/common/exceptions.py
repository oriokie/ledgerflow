"""One error shape for the entire API:

    {"error": {"code": "validation_error", "message": "...", "details": {...}}}

Domain exceptions (LedgerError, UnscopedAccessError, ...) are mapped here so
services can raise plain Python exceptions without knowing about HTTP.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler

from apps.common.tenant_context import UnscopedAccessError
from apps.ledger.services import LedgerError, UnbalancedEntryError

logger = logging.getLogger("ledgerflow.api")


def _plan_limit_exc():
    # Imported lazily-ish at module load; billing has no dependency on this
    # module, so there's no import cycle.
    from apps.billing.entitlements import PlanLimitExceeded

    return PlanLimitExceeded


def _separation_exc():
    from apps.platform_admin.separation import PlatformSeparationError

    return PlatformSeparationError


_DOMAIN_EXCEPTION_STATUS = {
    # 403 rather than 422: this is an authorization decision about who the
    # caller is, not a problem with what they submitted.
    _separation_exc(): status.HTTP_403_FORBIDDEN,
    UnbalancedEntryError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    LedgerError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    UnscopedAccessError: status.HTTP_403_FORBIDDEN,
    _plan_limit_exc(): status.HTTP_402_PAYMENT_REQUIRED,
}


def _error_body(code: str, message: str, details=None) -> dict:
    body = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body


def api_exception_handler(exc, context):
    # 1. Let DRF handle what it already understands (validation, auth, throttling...).
    response = drf_default_handler(exc, context)
    if response is not None:
        code = getattr(exc, "default_code", exc.__class__.__name__.lower())
        message = str(exc.detail) if hasattr(exc, "detail") else str(exc)
        details = exc.detail if isinstance(getattr(exc, "detail", None), (dict, list)) else None
        response.data = _error_body(code, message, details)
        return response

    # 2. Map our own domain exceptions.
    for exc_type, http_status in _DOMAIN_EXCEPTION_STATUS.items():
        if isinstance(exc, exc_type):
            return Response(_error_body(exc_type.__name__.lower(), str(exc)), status=http_status)

    # 3. Anything else is a genuine 500 — log it with full context, never leak internals.
    request = context.get("request")
    logger.exception(
        "Unhandled exception in API view",
        extra={"path": getattr(request, "path", None), "method": getattr(request, "method", None)},
    )
    return Response(
        _error_body("internal_error", "An unexpected error occurred."),
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
