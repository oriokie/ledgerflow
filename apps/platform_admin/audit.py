"""Recording side of the platform audit trail.

Every mutating platform service calls `record()`. It is a plain function
rather than a decorator or signal receiver because auditing a platform action
needs facts the caller has and a generic hook does not: the before/after diff
of the specific fields that changed, and the operator's stated reason.

`request_context()` extracts the transport-level facts once, at the API edge,
so services stay HTTP-free and can be driven equally from a Celery task or a
management command (where the context is simply empty).
"""

from __future__ import annotations

import logging
from typing import Any

from .models import PlatformAuditLog, PlatformStaff

logger = logging.getLogger("ledgerflow.platform.audit")


def request_context(request) -> dict[str, Any]:
    """Transport facts worth keeping on an audit row.

    `X-Forwarded-For` is read left-most-first because that is the original
    client; everything after it is proxy hops. This is only trustworthy behind
    a proxy that overwrites the header, which is the deployment assumption
    documented in `deploy/`.
    """
    if request is None:
        return {}
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    return {
        "ip_address": ip or None,
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:400],
        "request_id": getattr(request, "request_id", "") or "",
    }


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[Any]]:
    """Build a `{field: [old, new]}` change map, keeping only what moved.

    Recording unchanged fields would bury the one that mattered, and makes
    "what did this action actually do" unanswerable at a glance.
    """
    changes: dict[str, list[Any]] = {}
    for key in before.keys() | after.keys():
        old, new = before.get(key), after.get(key)
        if old != new:
            changes[key] = [_jsonable(old), _jsonable(new)]
    return changes


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def record(
    *,
    action: str,
    staff: PlatformStaff | None = None,
    module: str = "",
    target_type: str = "",
    target_id=None,
    tenant_id=None,
    changes: dict | None = None,
    reason: str = "",
    context: dict | None = None,
    request=None,
) -> PlatformAuditLog:
    """Append one row to the platform audit trail.

    Deliberately never raises for a *missing* optional field: an audit write
    that fails would either roll back a legitimate action or, worse, be caught
    and swallowed somewhere upstream. It does still participate in the caller's
    transaction, so an action that rolls back takes its audit row with it —
    the log records what happened, not what was attempted.
    """
    transport = request_context(request)
    transport_context = dict(context) if context else {}

    row = PlatformAuditLog.objects.create(
        actor_id=staff.user_id if staff else None,
        actor_email=(staff.user.email if staff and staff.user_id else "")[:254],
        actor_role=staff.role if staff else "",
        action=action,
        module=module,
        target_type=target_type,
        target_id=target_id,
        tenant_id=tenant_id,
        changes=changes or {},
        reason=reason or "",
        context=transport_context,
        **transport,
    )
    logger.info(
        "platform.audit %s",
        action,
        extra={
            "audit_action": action,
            "audit_actor": row.actor_email or "system",
            "audit_tenant": str(tenant_id) if tenant_id else None,
            "audit_target": f"{target_type}:{target_id}" if target_type else None,
        },
    )
    return row
