"""Secure tenant impersonation.

This is the only path by which platform staff can reach customer financial
data, so it is built to be narrow, loud and reversible:

* **Narrow.** A grant names one tenant, expires on its own, and is read-only
  unless someone deliberately says otherwise.
* **Loud.** Starting, using and ending a grant all produce audit rows. A reason
  is mandatory, and the grant cannot be created without one.
* **Reversible.** Every impersonated request re-reads the grant, so revoking it
  takes effect on the next call rather than whenever a token would have
  expired. A JWT claim alone could not offer this.

The token is a random secret whose SHA-256 hash is stored — the same discipline
as invitations and password-reset tokens. A database dump does not yield a
usable impersonation credential.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from contextlib import contextmanager

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant

from ..audit import record
from ..models import ImpersonationGrant, ImpersonationStatus, PlatformStaff
from ..rbac import PlatformCapability

logger = logging.getLogger("ledgerflow.platform.impersonation")

MODULE = "impersonation"


class ImpersonationError(Exception):
    """Raised when impersonation is refused or a grant is unusable."""


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@transaction.atomic
def start(
    *,
    staff: PlatformStaff,
    tenant_id,
    reason: str,
    read_only: bool = True,
    subject_user_id=None,
    ttl_minutes: int | None = None,
    request=None,
) -> tuple[ImpersonationGrant, str]:
    """Open an impersonation session. Returns `(grant, raw_token)`.

    The raw token is returned exactly once and never stored.
    """
    if not staff.has(PlatformCapability.TENANT_IMPERSONATE):
        raise ImpersonationError("You are not permitted to impersonate a workspace.")
    if not reason or len(reason.strip()) < 10:
        # A one-word reason ("support") is indistinguishable from no reason at
        # all when someone reviews this log in six months.
        raise ImpersonationError(
            "Impersonation needs a specific reason (at least 10 characters) — it will be audited."
        )

    from apps.tenancy.models import Tenant

    if not Tenant.objects.filter(id=tenant_id).exists():
        raise ImpersonationError("That workspace doesn't exist.")

    # One live grant per (staff, tenant): re-entering a workspace should reuse
    # the session rather than accumulate parallel ones that all need revoking.
    existing = ImpersonationGrant.objects.filter(
        staff=staff, tenant_id=tenant_id, status=ImpersonationStatus.ACTIVE
    ).first()
    if existing is not None and existing.is_usable:
        end(grant=existing, actor=staff, reason="Superseded by a new session.", request=request)

    raw_token = secrets.token_urlsafe(32)
    grant = ImpersonationGrant(
        staff=staff,
        tenant_id=tenant_id,
        subject_user_id=subject_user_id,
        reason=reason.strip(),
        read_only=read_only,
        token_hash=_hash(raw_token),
    )
    if ttl_minutes:
        from datetime import timedelta

        grant.expires_at = timezone.now() + timedelta(minutes=int(ttl_minutes))
    if request is not None:
        from ..permissions import client_ip

        grant.ip_address = client_ip(request)
    grant.save()

    record(
        action="impersonation.started",
        staff=staff,
        module=MODULE,
        target_type="tenancy.Tenant",
        target_id=tenant_id,
        tenant_id=tenant_id,
        changes={"read_only": [None, read_only]},
        reason=reason,
        context={"grant_id": str(grant.id), "expires_at": grant.expires_at.isoformat()},
        request=request,
    )
    logger.info("impersonation started: staff=%s tenant=%s", staff.user_id, tenant_id)
    return grant, raw_token


def resolve(*, raw_token: str) -> ImpersonationGrant:
    """Look up a grant by its token and confirm it is still usable.

    Lazily flips an elapsed grant to EXPIRED so the console shows the truth
    rather than a list of "active" sessions that all timed out yesterday.
    """
    grant = (
        ImpersonationGrant.objects.select_related("staff", "staff__user")
        .filter(token_hash=_hash(raw_token))
        .first()
    )
    if grant is None:
        raise ImpersonationError("That impersonation session isn't valid.")
    if grant.status == ImpersonationStatus.ACTIVE and grant.is_expired:
        grant.status = ImpersonationStatus.EXPIRED
        grant.ended_at = timezone.now()
        grant.save(update_fields=["status", "ended_at", "updated_at"])
    if not grant.is_usable:
        raise ImpersonationError(f"That impersonation session is {grant.status}.")
    if not grant.staff.is_active:
        raise ImpersonationError("The operator's platform access has been revoked.")
    return grant


def note_use(*, grant: ImpersonationGrant) -> None:
    """Count one request made under a grant.

    An `F()` update rather than read-modify-write: concurrent impersonated
    requests must each be counted, and the value is only ever displayed.
    """
    ImpersonationGrant.objects.filter(pk=grant.pk).update(request_count=F("request_count") + 1)


@contextmanager
def impersonate(*, grant: ImpersonationGrant):
    """Bind the tenant context for a grant.

    Wraps the same `bind_db_tenant` + `use_tenant` pair the tenant API layer
    uses, so impersonated reads are subject to exactly the RLS policy a real
    member's request would be — no bypass, no elevated role, no second code
    path that could drift from the first.
    """
    with transaction.atomic():
        bind_db_tenant(grant.tenant_id)
        actor_id = grant.subject_user_id or grant.staff.user_id
        with use_tenant(grant.tenant_id, actor_id=actor_id):
            note_use(grant=grant)
            yield grant


@transaction.atomic
def end(
    *, grant: ImpersonationGrant, actor: PlatformStaff | None = None, reason: str = "", request=None
) -> ImpersonationGrant:
    """Close a session normally."""
    if grant.status != ImpersonationStatus.ACTIVE:
        return grant
    grant.status = ImpersonationStatus.ENDED
    grant.ended_at = timezone.now()
    grant.save(update_fields=["status", "ended_at", "updated_at"])

    record(
        action="impersonation.ended",
        staff=actor or grant.staff,
        module=MODULE,
        target_type="tenancy.Tenant",
        target_id=grant.tenant_id,
        tenant_id=grant.tenant_id,
        reason=reason,
        context={"grant_id": str(grant.id), "requests_made": grant.request_count},
        request=request,
    )
    return grant


@transaction.atomic
def revoke(
    *, grant: ImpersonationGrant, actor: PlatformStaff, reason: str = "", request=None
) -> ImpersonationGrant:
    """Forcibly terminate someone else's session."""
    if grant.status != ImpersonationStatus.ACTIVE:
        return grant
    grant.status = ImpersonationStatus.REVOKED
    grant.ended_at = timezone.now()
    grant.revoked_by = actor.user
    grant.save(update_fields=["status", "ended_at", "revoked_by", "updated_at"])

    record(
        action="impersonation.revoked",
        staff=actor,
        module=MODULE,
        target_type="tenancy.Tenant",
        target_id=grant.tenant_id,
        tenant_id=grant.tenant_id,
        reason=reason,
        context={"grant_id": str(grant.id), "operator": grant.staff.user.email},
        request=request,
    )
    return grant


def revoke_all_for_staff(*, staff: PlatformStaff, actor: PlatformStaff, reason: str = "") -> int:
    """Terminate every live session held by one operator. Returns the count."""
    live = list(ImpersonationGrant.objects.filter(staff=staff, status=ImpersonationStatus.ACTIVE))
    for grant in live:
        revoke(grant=grant, actor=actor, reason=reason)
    return len(live)


def expire_stale(*, now=None) -> int:
    """Sweep elapsed grants. Returns how many were closed.

    Belt-and-braces alongside the lazy expiry in `resolve`: a session that is
    never used again would otherwise sit in the console reading "active"
    indefinitely.
    """
    now = now or timezone.now()
    return ImpersonationGrant.objects.filter(status=ImpersonationStatus.ACTIVE, expires_at__lte=now).update(
        status=ImpersonationStatus.EXPIRED, ended_at=now, updated_at=now
    )


def active_sessions():
    return (
        ImpersonationGrant.objects.filter(status=ImpersonationStatus.ACTIVE, expires_at__gt=timezone.now())
        .select_related("staff", "staff__user")
        .order_by("-created_at")
    )
