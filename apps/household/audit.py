"""Recording what happened, so the household can see it later.

One function, `record()`, called from the services that change things. That is
a deliberate choice over the two obvious alternatives:

**Not signals.** Django signals would catch every write automatically, which
sounds like exactly what an audit log wants and is not. A signal fires on the
row, so it knows a `Goal` was updated and nothing about *why* — and "Amina
raised the house deposit target from 2m to 2.5m" is the entry worth having,
while "goal.updated" is noise that trains people to ignore the log. Summaries
are written where the intent is known.

**Not middleware.** Request-level logging records endpoints, not decisions, and
misses everything a Celery task does.

The cost of calling it by hand is that a call site can forget. That is real,
and the mitigation is that the events worth auditing are concentrated in a
handful of service functions rather than scattered — plus `test_audit.py`
asserts the specific ones the household relies on.

**Failures here never break the caller.** An audit write that raises would mean
a partner could not pay a bill because the log was full, which trades a serious
failure for a cosmetic one. Errors are swallowed and reported to the error
tracker; the alternative is worse.
"""

from __future__ import annotations

import logging
import uuid

from django.db import transaction as db_transaction

from apps.common.tenant_context import get_current_actor_id

from .models import AuditAction, AuditEvent

logger = logging.getLogger("ledgerflow.household.audit")


def record(
    *,
    action: str,
    subject_type: str,
    summary: str,
    subject_id: uuid.UUID | str | None = None,
    detail: dict | None = None,
    is_private: bool = False,
    actor_id: uuid.UUID | str | None = None,
) -> AuditEvent | None:
    """Append one event. Returns None if it could not be written.

    `summary` should read as a complete sentence to somebody scanning a
    timeline six months from now — "Amina set the shared split to 60/40", not
    "agreement.updated". It is stored rather than re-rendered, so the entry
    keeps saying what it said when it was made.
    """
    try:
        # Resolved to a *real* user or to None. Writing an id that does not
        # exist would violate the foreign key — and Django creates FKs as
        # DEFERRABLE INITIALLY DEFERRED, so that violation is raised at commit,
        # long after this function has returned and somewhere no `except` here
        # can reach it. The caller would see their own transaction fail for a
        # reason that has nothing to do with what they were doing. Checking up
        # front is the only place this can be handled.
        actor, label = _resolve_actor(actor_id or get_current_actor_id())
        # The savepoint covers the rest. Catching the exception is not enough on
        # its own: a failed INSERT marks the surrounding transaction as broken,
        # so every subsequent query the *caller* makes raises
        # TransactionManagementError. Swallowing the error without a savepoint
        # would still break the thing this is trying not to break — just
        # further away, where it is harder to trace back to the log.
        with db_transaction.atomic():
            return AuditEvent.objects.create(
                actor_id=actor,
                actor_label=label,
                action=action,
                subject_type=subject_type,
                subject_id=_as_uuid(subject_id),
                summary=summary[:255],
                detail=detail or {},
                is_private=is_private,
            )
    except Exception:  # noqa: BLE001 — logging must not break the thing it logs
        logger.exception("Could not record household audit event: %s", summary)
        return None


def _as_uuid(value) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _resolve_actor(actor_id) -> tuple[uuid.UUID | None, str]:
    """Turn a claimed actor into a real user id and a display label.

    Returns `(None, label)` when the id names nobody — an event by an
    unidentifiable actor is still an event worth recording, and recording it
    with a dangling foreign key is not an option (see `record`). The label is
    denormalised on purpose so the log still names a person after the account
    is closed and the FK nulls out.
    """
    if not actor_id:
        return None, "System"
    try:
        from apps.household.models import HouseholdProfile
        from apps.tenancy.models import Membership

        membership = Membership.objects.filter(user_id=actor_id).select_related("user").first()
        if membership is None:
            return None, "Someone"

        profile = HouseholdProfile.objects.filter(membership_id=membership.id).first()
        if profile and profile.display_name:
            return membership.user_id, profile.display_name
        email = getattr(membership.user, "email", "") or ""
        return membership.user_id, (email.split("@")[0] if email else "Someone")
    except Exception:  # noqa: BLE001
        return None, "Someone"


def timeline(*, limit: int = 100, subject_type: str | None = None) -> list[AuditEvent]:
    """The household's activity, most recent first.

    Private events are included: hiding them would leave gaps that are
    themselves informative, and the summary of a private event is written
    without its specifics precisely so it can be shown. What a partner learns
    is that *something* happened on an account they cannot see — which is the
    honest state of affairs, and better than a timeline that silently omits.
    """
    queryset = AuditEvent.objects.all()
    if subject_type:
        queryset = queryset.filter(subject_type=subject_type)
    return list(queryset[:limit])


__all__ = ["AuditAction", "record", "timeline"]
