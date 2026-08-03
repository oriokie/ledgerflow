"""Appointing, adjusting and revoking platform staff.

Every function here is audited, because "who was given authority over customer
accounts, by whom, and when" is the question a security review starts with.

The privilege-escalation guard is the substantive rule: a staff member may not
grant a capability they do not themselves hold. Without it, anyone with
`staff.manage` is effectively a Platform Owner — they need only appoint a
colleague with full capabilities, or edit their own row.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from ..audit import record
from ..models import PlatformStaff
from ..rbac import (
    ALL_CAPABILITIES,
    PlatformCapability,
    PlatformRole,
    UnknownCapabilityError,
    capabilities_for,
    parse_capabilities,
)

MODULE = "staff"


class StaffError(Exception):
    """Raised for invalid staff-management operations."""


def _validate_overrides(extra, denied) -> None:
    try:
        parse_capabilities(extra)
        parse_capabilities(denied)
    except UnknownCapabilityError as exc:
        raise StaffError(str(exc)) from exc


def _guard_escalation(*, actor: PlatformStaff | None, granting: frozenset) -> None:
    """Refuse to hand out authority the actor does not hold.

    Skipped when `actor` is None, which is the bootstrap path (a management
    command creating the first owner). That is the one moment where no existing
    staff member exists to authorise the grant, and it is deliberately only
    reachable from the server console, never over HTTP.
    """
    if actor is None:
        return
    excess = granting - actor.capabilities
    if excess:
        names = ", ".join(sorted(str(c) for c in excess))
        raise StaffError(f"You cannot grant capabilities you don't hold yourself: {names}.")


@transaction.atomic
def appoint(
    *,
    user,
    role: str,
    actor: PlatformStaff | None = None,
    extra_capabilities: list | None = None,
    denied_capabilities: list | None = None,
    allowed_ips: list | None = None,
    require_mfa: bool = True,
    note: str = "",
    request=None,
) -> PlatformStaff:
    """Grant a user platform authority."""
    if PlatformStaff.objects.filter(user=user).exists():
        raise StaffError("That user is already platform staff; update their role instead.")
    try:
        PlatformRole(role)
    except ValueError as exc:
        raise StaffError(f"{role!r} is not a known platform role.") from exc

    _validate_overrides(extra_capabilities, denied_capabilities)
    _guard_escalation(
        actor=actor,
        granting=capabilities_for(role, extra=extra_capabilities, denied=denied_capabilities),
    )

    # Pre-existing customer memberships are recorded, not severed. Removing
    # someone from their own household because they were given a support role
    # would be a startling side effect of a permissions change, and their data
    # is not ours to delete. The audit row makes the overlap visible so an
    # operator can resolve it deliberately.
    from ..separation import existing_memberships

    overlap = existing_memberships(user)

    staff = PlatformStaff.objects.create(
        user=user,
        role=role,
        extra_capabilities=list(extra_capabilities or []),
        denied_capabilities=list(denied_capabilities or []),
        allowed_ips=list(allowed_ips or []),
        require_mfa=require_mfa,
        note=note,
        granted_by=actor.user if actor else None,
    )
    record(
        action="staff.appointed",
        staff=actor,
        module=MODULE,
        target_type="platform_admin.PlatformStaff",
        target_id=staff.id,
        changes={"role": [None, role], "user": [None, user.email]},
        reason=note,
        context={"pre_existing_workspace_memberships": overlap} if overlap else {},
        request=request,
    )
    return staff


@transaction.atomic
def update(
    *,
    staff: PlatformStaff,
    actor: PlatformStaff,
    role: str | None = None,
    extra_capabilities: list | None = None,
    denied_capabilities: list | None = None,
    allowed_ips: list | None = None,
    require_mfa: bool | None = None,
    reason: str = "",
    request=None,
) -> PlatformStaff:
    """Adjust an existing staff member's authority."""
    if staff.id == actor.id and role is not None and role != staff.role:
        # Self-promotion is the shortest path from `staff.manage` to owner.
        raise StaffError("You cannot change your own platform role.")

    before = {
        "role": staff.role,
        "extra_capabilities": sorted(staff.extra_capabilities or []),
        "denied_capabilities": sorted(staff.denied_capabilities or []),
        "allowed_ips": sorted(staff.allowed_ips or []),
        "require_mfa": staff.require_mfa,
    }

    if role is not None:
        try:
            PlatformRole(role)
        except ValueError as exc:
            raise StaffError(f"{role!r} is not a known platform role.") from exc
        staff.role = role
    if extra_capabilities is not None:
        staff.extra_capabilities = list(extra_capabilities)
    if denied_capabilities is not None:
        staff.denied_capabilities = list(denied_capabilities)
    if allowed_ips is not None:
        staff.allowed_ips = list(allowed_ips)
    if require_mfa is not None:
        staff.require_mfa = require_mfa

    _validate_overrides(staff.extra_capabilities, staff.denied_capabilities)
    _guard_escalation(actor=actor, granting=staff.capabilities)

    staff.save(
        update_fields=[
            "role",
            "extra_capabilities",
            "denied_capabilities",
            "allowed_ips",
            "require_mfa",
            "updated_at",
        ]
    )

    after = {
        "role": staff.role,
        "extra_capabilities": sorted(staff.extra_capabilities or []),
        "denied_capabilities": sorted(staff.denied_capabilities or []),
        "allowed_ips": sorted(staff.allowed_ips or []),
        "require_mfa": staff.require_mfa,
    }
    record(
        action="staff.updated",
        staff=actor,
        module=MODULE,
        target_type="platform_admin.PlatformStaff",
        target_id=staff.id,
        changes={k: [before[k], after[k]] for k in before if before[k] != after[k]},
        reason=reason,
        request=request,
    )
    return staff


@transaction.atomic
def revoke(*, staff: PlatformStaff, actor: PlatformStaff, reason: str = "", request=None) -> PlatformStaff:
    """Deactivate a staff member and end any impersonation they hold.

    Ending live impersonations is the point of doing this in a service rather
    than flipping a boolean: revoking someone's access while they are inside a
    customer's workspace has to close that door too, or the revocation is
    cosmetic until their session happens to expire.
    """
    from .impersonation import revoke_all_for_staff

    if staff.id == actor.id:
        raise StaffError("You cannot revoke your own platform access.")
    if staff.role == PlatformRole.OWNER and not actor.has(PlatformCapability.STAFF_MANAGE):
        raise StaffError("Only an owner can revoke another owner.")
    if (
        staff.role == PlatformRole.OWNER
        and PlatformStaff.objects.filter(role=PlatformRole.OWNER, is_active=True).count() <= 1
    ):
        # The same reasoning as tenancy's last-owner rule: a platform with no
        # owner has no one who can appoint one.
        raise StaffError("This is the last active platform owner; appoint another first.")

    staff.is_active = False
    staff.save(update_fields=["is_active", "updated_at"])
    ended = revoke_all_for_staff(staff=staff, actor=actor, reason="Platform access revoked.")

    record(
        action="staff.revoked",
        staff=actor,
        module=MODULE,
        target_type="platform_admin.PlatformStaff",
        target_id=staff.id,
        changes={"is_active": [True, False]},
        reason=reason,
        context={"impersonations_ended": ended},
        request=request,
    )
    return staff


@transaction.atomic
def reinstate(*, staff: PlatformStaff, actor: PlatformStaff, reason: str = "", request=None):
    staff.is_active = True
    staff.save(update_fields=["is_active", "updated_at"])
    record(
        action="staff.reinstated",
        staff=actor,
        module=MODULE,
        target_type="platform_admin.PlatformStaff",
        target_id=staff.id,
        changes={"is_active": [False, True]},
        reason=reason,
        request=request,
    )
    return staff


def touch_last_seen(*, staff: PlatformStaff) -> None:
    """Stamp activity. Deliberately outside any audit trail — a heartbeat is
    not an action, and writing one audit row per request would drown the log
    that matters."""
    PlatformStaff.objects.filter(pk=staff.pk).update(last_seen_at=timezone.now())


def capability_catalog() -> list[dict]:
    """Every capability with the roles that hold it — the data behind the
    RBAC matrix in the admin UI."""
    from ..rbac import ROLE_CAPABILITIES

    return [
        {
            "capability": str(capability),
            "module": str(capability).split(".")[0],
            "roles": sorted(str(role) for role, caps in ROLE_CAPABILITIES.items() if capability in caps),
        }
        for capability in sorted(ALL_CAPABILITIES, key=str)
    ]
