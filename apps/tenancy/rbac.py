"""Role-based access control: capability mapping.

A fixed role hierarchy (VIEWER < MEMBER < ADMIN < OWNER) with capabilities
attached to each -- not fully custom/attribute-based roles. That's a
deliberate scope decision: custom per-tenant roles are a real enterprise
feature but a materially bigger one (role CRUD, migrating existing
memberships when a role is edited or deleted, UI for building permission
sets). The fixed hierarchy covers the actual access patterns of a
personal-finance product; `has_capability` is the seam where a future
custom-roles system would plug in without changing any call site -- callers
ask "can this membership do X", never "is this role >= Y" directly, except
where the check is genuinely about seniority (e.g. "can only be removed by
someone with a higher role").
"""

from __future__ import annotations

from enum import StrEnum

from .models import Membership, Role

ROLE_ORDER: dict[str, int] = {Role.VIEWER: 0, Role.MEMBER: 1, Role.ADMIN: 2, Role.OWNER: 3}


class Capability(StrEnum):
    LEDGER_READ = "ledger.read"
    LEDGER_WRITE = "ledger.write"
    WORKSPACE_READ = "workspace.read"
    WORKSPACE_MANAGE_MEMBERS = "workspace.manage_members"
    WORKSPACE_MANAGE_INVITATIONS = "workspace.manage_invitations"
    WORKSPACE_MANAGE_SETTINGS = "workspace.manage_settings"
    WORKSPACE_MANAGE_BILLING = "workspace.manage_billing"
    WORKSPACE_DELETE = "workspace.delete"


ROLE_CAPABILITIES: dict[str, frozenset[Capability]] = {
    Role.VIEWER: frozenset({Capability.LEDGER_READ, Capability.WORKSPACE_READ}),
    Role.MEMBER: frozenset({Capability.LEDGER_READ, Capability.LEDGER_WRITE, Capability.WORKSPACE_READ}),
    Role.ADMIN: frozenset(
        {
            Capability.LEDGER_READ,
            Capability.LEDGER_WRITE,
            Capability.WORKSPACE_READ,
            Capability.WORKSPACE_MANAGE_MEMBERS,
            Capability.WORKSPACE_MANAGE_INVITATIONS,
            Capability.WORKSPACE_MANAGE_SETTINGS,
        }
    ),
    Role.OWNER: frozenset(
        {
            Capability.LEDGER_READ,
            Capability.LEDGER_WRITE,
            Capability.WORKSPACE_READ,
            Capability.WORKSPACE_MANAGE_MEMBERS,
            Capability.WORKSPACE_MANAGE_INVITATIONS,
            Capability.WORKSPACE_MANAGE_SETTINGS,
            Capability.WORKSPACE_MANAGE_BILLING,
            Capability.WORKSPACE_DELETE,
        }
    ),
}


def has_role_at_least(membership: Membership | None, minimum: str) -> bool:
    return membership is not None and ROLE_ORDER[membership.role] >= ROLE_ORDER[minimum]


def has_capability(membership: Membership | None, capability: Capability) -> bool:
    if membership is None:
        return False
    return capability in ROLE_CAPABILITIES[membership.role]


def outranks(a: Membership, b: Membership) -> bool:
    """True if membership `a` has strictly greater seniority than `b` — used
    for actions like "remove a member" or "change someone's role", where the
    rule isn't a fixed capability but a relative one (an admin can't demote
    the owner)."""
    return ROLE_ORDER[a.role] > ROLE_ORDER[b.role]
