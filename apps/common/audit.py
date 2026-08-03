"""Financial/security audit trail.

Distinct from OutboxEvent (which exists to reliably *deliver* events to
consumers). AuditLog is the human- and compliance-facing record of *who did
what to which record*, with a before/after diff. Append-only; protected by the
same immutability trigger as the ledger.
"""

from __future__ import annotations

import logging as _logging

from django.db import models

from .ids import uuid7
from .tenant_context import get_current_actor_id, get_current_tenant_id


class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant_id = models.UUIDField(db_index=True, editable=False)
    actor_id = models.UUIDField(null=True, blank=True, editable=False)  # null = system
    action = models.CharField(max_length=64)  # e.g. "transaction.recategorized"
    target_type = models.CharField(max_length=64)  # e.g. "finance.Transaction"
    #: Nullable because an action can legitimately span many rows — reconciling
    #: a whole statement is one decision over fifty transactions, and writing
    #: fifty audit rows would bury the actions that name a single object. The
    #: platform trail models it the same way.
    target_id = models.UUIDField(null=True, blank=True)
    changes = models.JSONField(default=dict)  # {"field": [old, new], ...}
    context = models.JSONField(default=dict)  # ip, user agent, request id
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "target_type", "target_id"]),
            models.Index(fields=["tenant_id", "actor_id", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.target_type}:{self.target_id}"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
# The model above, and the immutability trigger protecting it, shipped without
# a single caller — 68 mutating service functions recorded nothing, so a shared
# household workspace could not answer "who deleted this account". These helpers
# close that, and deliberately mirror `apps.platform_admin.audit` so the two
# trails have one shape and one viewer component can render both.
#
# `record()` is a plain function rather than a signal receiver because a useful
# audit row needs facts a generic hook does not have: which fields actually
# changed, and the actor's intent. A post_save receiver can see the former only
# by refetching, and never the latter.

_audit_logger = _logging.getLogger("ledgerflow.audit")


def diff(before: dict, after: dict) -> dict[str, list]:
    """Build `{field: [old, new]}`, keeping only what moved.

    Unchanged fields are dropped: recording them buries the one that mattered
    and makes "what did this actually do" unanswerable at a glance.
    """
    out: dict[str, list] = {}
    for key in before.keys() | after.keys():
        old, new = before.get(key), after.get(key)
        if old != new:
            out[key] = [_jsonable(old), _jsonable(new)]
    return out


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def snapshot(instance, fields: list[str]) -> dict:
    """Read `fields` off a model instance, for diffing around a mutation."""
    return {f: _jsonable(getattr(instance, f, None)) for f in fields}


#: Distinguishes "caller didn't say" from "caller said: no actor". Without it,
#: `actor_id=None` fell through to the ambient request actor, so an automation
#: rule firing *during* a user's request was attributed to the user — which is
#: precisely backwards for the case the distinction exists to serve.
UNSET = object()


def record(
    *,
    action: str,
    target: object = None,
    target_type: str = "",
    target_id=None,
    changes: dict | None = None,
    actor_id=UNSET,
    tenant_id=None,
    context: dict | None = None,
) -> AuditLog | None:
    """Append one row to the workspace audit trail.

    Tenant and actor default to the ambient request context, so ordinary
    service code calls this with just an action and a target.

    Returns None — rather than raising — when there is no tenant bound. Audit
    writing must never be the reason a legitimate operation fails, and several
    services are reachable from management commands and Celery tasks where no
    request context exists. The miss is logged so it is visible.

    Isolation note: this table is deliberately **not** RLS-protected — see the
    rationale in `ledger/migrations/0002_financial_integrity.py`. It is written
    during operations that predate a per-request tenant GUC (workspace
    creation, invitation acceptance) and read cross-tenant by trusted workers,
    so a policy here would reject the writes it most needs to capture. Scoping
    is therefore the caller's responsibility: **any endpoint that exposes these
    rows must filter on `tenant_id` explicitly.** No such endpoint exists yet.
    """
    resolved_tenant = tenant_id or get_current_tenant_id()
    if resolved_tenant is None:
        _audit_logger.warning("audit %s skipped: no tenant bound", action)
        return None

    if target is not None:
        target_type = target_type or f"{target._meta.app_label}.{target.__class__.__name__}"
        target_id = target_id or getattr(target, "pk", None)

    row = AuditLog.objects.create(
        tenant_id=resolved_tenant,
        actor_id=get_current_actor_id() if actor_id is UNSET else actor_id,
        action=action,
        target_type=target_type[:64],
        target_id=target_id,
        changes=changes or {},
        context=context or {},
    )
    _audit_logger.info(
        "audit %s", action,
        extra={"audit_action": action, "audit_target": f"{target_type}:{target_id}"},
    )
    return row
