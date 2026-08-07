"""Tenancy service layer -- the ONLY place workspace/membership/invitation
state mutates. Views never write models directly; they call these functions.
Each mutating operation is atomic and emits an outbox event.
"""

from __future__ import annotations

import hashlib
import logging

from django.db import transaction

from apps.common import audit
from apps.common.outbox import OutboxEvent

from .models import (
    Invitation,
    InvitationStatus,
    Membership,
    Role,
    Tenant,
    TenantType,
    _generate_invitation_token,
)
from .rbac import ROLE_ORDER, Capability, has_capability, outranks


class TenancyError(Exception):
    pass


class InvalidInvitationError(TenancyError):
    pass


class InsufficientRoleError(TenancyError):
    pass


class LastOwnerError(TenancyError):
    """Raised when an action would leave a workspace with no OWNER."""


@transaction.atomic
def update_workspace(
    *,
    tenant: Tenant,
    actor_membership: Membership,
    name: str | None = None,
    base_currency: str | None = None,
    block_overdrafts: bool | None = None,
) -> Tenant:
    """Owner-only workspace settings update. Changing the base currency only
    affects how new categories/reporting default and how mixed-currency totals
    consolidate — existing transactions keep their own currency untouched."""
    # Local imports: `create_workspace` takes a `timezone` *parameter*, so a
    # module-level `from django.utils import timezone` would be shadowed there.
    from django.utils import timezone

    from apps.fx.currencies import is_supported

    if not has_capability(actor_membership, Capability.WORKSPACE_MANAGE_MEMBERS):
        raise InsufficientRoleError("Only an owner or admin can change workspace settings.")

    fields: list[str] = []
    if name is not None and name.strip():
        tenant.name = name.strip()
        fields.append("name")
    if base_currency is not None:
        code = base_currency.upper()
        if not is_supported(code):
            raise TenancyError(f"{code} isn't a supported currency.")
        tenant.base_currency = code
        fields.append("base_currency")
        # Setting it through this path is always a deliberate act — settings or
        # the first-run checklist — so it also records *that a choice was made*.
        # Re-confirming the same code still counts: the point is that somebody
        # was asked and answered, not that the answer changed.
        tenant.base_currency_chosen_at = timezone.now()
        fields.append("base_currency_chosen_at")
    if block_overdrafts is not None:
        # Turning this off never rewrites anything already posted — it only
        # changes what the product will accept from here on.
        tenant.block_overdrafts = block_overdrafts
        fields.append("block_overdrafts")
    if fields:
        fields.append("updated_at")
        tenant.save(update_fields=fields)
    return tenant


@transaction.atomic
def close_workspace(*, tenant: Tenant, actor_membership: Membership) -> Tenant:
    """Soft-close a workspace. Audited: this is the most consequential thing a
    workspace owner can do, and it is reversible only inside the grace period."""
    """Owner-initiated workspace closure. Soft-closes the workspace (it leaves
    every member's list immediately and access is revoked) and emits an event a
    purge worker consumes for full data erasure after any grace period. Kept
    reversible at the data layer on purpose — irreversible hard-deletion is a
    deliberate, asynchronous step, not a synchronous button press."""
    if not has_capability(actor_membership, Capability.WORKSPACE_DELETE):
        raise InsufficientRoleError("Only an owner can close a workspace.")
    if actor_membership.tenant_id != tenant.id:
        raise TenancyError("You can only close your own workspace.")

    tenant.is_active = False
    tenant.save(update_fields=["is_active", "updated_at"])
    OutboxEvent.objects.create(
        tenant_id=tenant.id,
        aggregate_type="tenancy.Tenant",
        aggregate_id=tenant.id,
        event_type="tenancy.workspace.closed",
        payload={"closed_by": str(actor_membership.user_id)},
    )
    audit.record(
        action="workspace.closed",
        target=tenant,
        changes={"is_active": [True, False]},
        actor_id=actor_membership.user_id,
        tenant_id=tenant.id,
    )
    return tenant


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


@transaction.atomic
def create_workspace(
    *,
    name: str,
    owner,
    type: str = TenantType.PERSONAL,  # noqa: A002 -- matches the public API vocabulary
    base_currency: str = "USD",
    locale: str = "en-US",
    timezone: str = "UTC",
) -> Tenant:
    # A platform operator account is for acting on other people's workspaces,
    # not for owning one. See apps.platform_admin.separation for why.
    from apps.platform_admin.separation import assert_may_join_workspace

    assert_may_join_workspace(owner, action="create a workspace")

    tenant = Tenant.objects.create(
        name=name,
        type=type,
        base_currency=base_currency,
        default_locale=locale,
        default_timezone=timezone,
    )
    Membership.objects.create(tenant=tenant, user=owner, role=Role.OWNER)
    OutboxEvent.objects.create(
        tenant_id=tenant.id,
        aggregate_type="tenancy.Tenant",
        aggregate_id=tenant.id,
        event_type="tenancy.workspace.created",
        payload={"name": name, "type": type, "owner_id": str(owner.id), "base_currency": base_currency},
    )
    _seed_default_categories(tenant=tenant, owner=owner, currency=base_currency)

    # Every new workspace starts on the Basic trial — card-free, seven days.
    # Best-effort but loud: a billing hiccup must not block someone's first
    # minute in the product, and a workspace without a subscription simply
    # behaves as legacy-unmetered until an operator looks.
    try:
        from apps.billing.services import start_trial

        start_trial(tenant_id=tenant.id)
    except Exception:  # noqa: BLE001
        logger.exception("Could not start the trial for workspace %s", tenant.id)

    return tenant


logger = logging.getLogger(__name__)

# A starter taxonomy so a brand-new workspace owner can categorize their first
# transaction immediately, instead of having to invent categories first.
DEFAULT_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("Housing", "expense"),
    ("Groceries", "expense"),
    ("Dining out", "expense"),
    ("Transport", "expense"),
    ("Utilities", "expense"),
    ("Health", "expense"),
    ("Entertainment", "expense"),
    ("Shopping", "expense"),
    ("Salary", "income"),
    ("Other income", "income"),
)


def _seed_default_categories(*, tenant: Tenant, owner, currency: str) -> None:
    """Best-effort starter categories for a new workspace. Runs in its own
    savepoint under the new tenant's context — if anything goes wrong it's
    rolled back and logged, never allowed to fail the signup it's part of."""
    from apps.common.rls import bind_db_tenant
    from apps.common.tenant_context import use_tenant
    from apps.finance import services as finance_services

    try:
        with transaction.atomic(), use_tenant(tenant.id, owner.id):
            bind_db_tenant(tenant.id)
            for cat_name, kind in DEFAULT_CATEGORIES:
                finance_services.create_category(name=cat_name, kind=kind, currency=currency)
    except Exception:  # noqa: BLE001 - defensive: seeding must never break workspace creation
        logger.exception("Failed to seed default categories for tenant %s", tenant.id)


@transaction.atomic
def add_member(*, tenant: Tenant, user, role: str = Role.MEMBER) -> Membership:
    from apps.billing.entitlements import ensure_can_add_member, lock_tenant_for_limit_check

    # Lock before counting: without it two concurrent joins both read the
    # pre-change seat count and both pass a limit that only had room for one.
    lock_tenant_for_limit_check(tenant.id)
    ensure_can_add_member(
        tenant_id=tenant.id,
        current_count=Membership.objects.filter(tenant=tenant).count(),
    )
    membership = Membership.objects.create(tenant=tenant, user=user, role=role)
    OutboxEvent.objects.create(
        tenant_id=tenant.id,
        aggregate_type="tenancy.Membership",
        aggregate_id=membership.id,
        event_type="tenancy.member.added",
        payload={"user_id": str(user.id), "role": role},
    )
    return membership


def _can_act_on(actor: Membership, target: Membership) -> bool:
    """Owners sit at the ceiling of the hierarchy and may manage each other
    (e.g. co-founders resolving a dispute, incident response) — everyone
    else needs strict seniority over the person they're acting on."""
    return actor.role == Role.OWNER or outranks(actor, target)


@transaction.atomic
def change_member_role(
    *, actor_membership: Membership, target_membership: Membership, new_role: str
) -> Membership:
    if target_membership.tenant_id != actor_membership.tenant_id:
        raise TenancyError("Membership does not belong to this workspace.")
    is_self = actor_membership.id == target_membership.id
    if not is_self:
        if not has_capability(actor_membership, Capability.WORKSPACE_MANAGE_MEMBERS):
            raise InsufficientRoleError("You do not have permission to manage members.")
        if not _can_act_on(actor_membership, target_membership):
            raise InsufficientRoleError("You can only manage members with a lower role than your own.")
    if ROLE_ORDER[new_role] > ROLE_ORDER[actor_membership.role]:
        raise InsufficientRoleError("You cannot grant a role higher than your own.")
    if target_membership.role == Role.OWNER and new_role != Role.OWNER:
        remaining_owners = Membership.objects.filter(
            tenant_id=target_membership.tenant_id, role=Role.OWNER
        ).exclude(id=target_membership.id)
        if not remaining_owners.exists():
            raise LastOwnerError("A workspace must always have at least one owner.")

    previous_role = target_membership.role
    target_membership.role = new_role
    target_membership.save(update_fields=["role", "updated_at"])
    OutboxEvent.objects.create(
        tenant_id=target_membership.tenant_id,
        aggregate_type="tenancy.Membership",
        aggregate_id=target_membership.id,
        event_type="tenancy.member.role_changed",
        payload={"user_id": str(target_membership.user_id), "new_role": new_role},
    )
    audit.record(
        action="member.role_changed",
        target_type="tenancy.Membership",
        target_id=target_membership.id,
        changes={"role": [previous_role, new_role]},
        actor_id=actor_membership.user_id,
        tenant_id=target_membership.tenant_id,
    )
    return target_membership


@transaction.atomic
def remove_member(*, actor_membership: Membership, target_membership: Membership) -> None:
    if target_membership.tenant_id != actor_membership.tenant_id:
        raise TenancyError("Membership does not belong to this workspace.")
    is_self = actor_membership.id == target_membership.id
    if not is_self:
        if not has_capability(actor_membership, Capability.WORKSPACE_MANAGE_MEMBERS):
            raise InsufficientRoleError("You do not have permission to manage members.")
        if not _can_act_on(actor_membership, target_membership):
            raise InsufficientRoleError("You can only remove members with a lower role than your own.")
    if target_membership.role == Role.OWNER:
        remaining_owners = Membership.objects.filter(
            tenant_id=target_membership.tenant_id, role=Role.OWNER
        ).exclude(id=target_membership.id)
        if not remaining_owners.exists():
            raise LastOwnerError("A workspace must always have at least one owner.")

    tenant_id, user_id, membership_id = (
        target_membership.tenant_id,
        target_membership.user_id,
        target_membership.id,
    )
    removed_role = target_membership.role
    target_membership.delete()
    OutboxEvent.objects.create(
        tenant_id=tenant_id,
        aggregate_type="tenancy.Membership",
        aggregate_id=membership_id,
        event_type="tenancy.member.removed",
        payload={"user_id": str(user_id)},
    )
    audit.record(
        action="member.removed",
        target_type="tenancy.Membership",
        target_id=membership_id,
        changes={"role": [removed_role, None]},
        actor_id=actor_membership.user_id,
        tenant_id=tenant_id,
    )


@transaction.atomic
def create_invitation(
    *, tenant: Tenant, invited_by_membership: Membership, email: str, role: str
) -> tuple[Invitation, str]:
    """Returns (invitation, raw_token). The raw token is shown to the caller
    exactly once -- only its hash is persisted."""
    if not has_capability(invited_by_membership, Capability.WORKSPACE_MANAGE_INVITATIONS):
        raise InsufficientRoleError("You do not have permission to invite members.")
    if ROLE_ORDER[role] > ROLE_ORDER[invited_by_membership.role]:
        raise InsufficientRoleError("You cannot invite someone to a role higher than your own.")

    # Fail early if the workspace has no seats left, counting members already in
    # plus invitations still outstanding — so an owner isn't told only at accept.
    from apps.billing.entitlements import ensure_can_add_member, lock_tenant_for_limit_check

    lock_tenant_for_limit_check(tenant.id)
    pending = Invitation.objects.filter(tenant=tenant, status=InvitationStatus.PENDING).count()
    ensure_can_add_member(
        tenant_id=tenant.id,
        current_count=Membership.objects.filter(tenant=tenant).count() + pending,
    )

    email = email.strip().lower()
    raw_token = _generate_invitation_token()
    invitation = Invitation.objects.create(
        tenant=tenant,
        email=email,
        role=role,
        invited_by=invited_by_membership.user,
        token_hash=_hash_token(raw_token),
    )
    OutboxEvent.objects.create(
        tenant_id=tenant.id,
        aggregate_type="tenancy.Invitation",
        aggregate_id=invitation.id,
        event_type="tenancy.invitation.created",
        payload={"email": email, "role": role},
    )
    from .tasks import send_invitation_email

    # Queued *after* commit. A worker runs in another process on another
    # connection, so dispatching inline raced the commit: the task looked the
    # invitation up, did not find it, and returned silently — the inviter saw
    # success and the invitee received nothing. `on_commit` also means a
    # rolled-back invitation never emails anyone a token that will not work.
    transaction.on_commit(
        lambda: send_invitation_email.delay(invitation_id=str(invitation.id), raw_token=raw_token)
    )
    return invitation, raw_token


def get_invitation_preview(*, raw_token: str) -> Invitation:
    """Look up an invitation by its raw token without redeeming it.

    Lets an invitee see what they're being asked to join -- workspace,
    inviter, role -- before they commit. Deliberately read-only and doesn't
    require the caller to be authenticated or to match the invited email:
    that check only matters at accept time.
    """
    token_hash = _hash_token(raw_token)
    invitation = Invitation.objects.select_related("tenant", "invited_by").filter(token_hash=token_hash).first()
    if invitation is None or not invitation.is_pending:
        raise InvalidInvitationError("This invitation is invalid, expired, or has already been used.")
    return invitation


@transaction.atomic
def accept_invitation(*, raw_token: str, user) -> Membership:
    """Redeem an invitation. Platform staff are barred — see `create_workspace`."""
    from apps.platform_admin.separation import assert_may_join_workspace

    assert_may_join_workspace(user, action="accept a workspace invitation")

    token_hash = _hash_token(raw_token)
    invitation = Invitation.objects.select_for_update().filter(token_hash=token_hash).first()
    if invitation is None or not invitation.is_pending:
        raise InvalidInvitationError("This invitation is invalid, expired, or has already been used.")
    if invitation.email != user.email.lower():
        raise InvalidInvitationError("This invitation was sent to a different email address.")
    if Membership.objects.filter(tenant=invitation.tenant, user=user).exists():
        raise InvalidInvitationError("You are already a member of this workspace.")

    from django.utils import timezone

    membership = add_member(tenant=invitation.tenant, user=user, role=invitation.role)
    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_by = user
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["status", "accepted_by", "accepted_at", "updated_at"])
    return membership


@transaction.atomic
def revoke_invitation(*, invitation: Invitation, actor_membership: Membership) -> Invitation:
    if not has_capability(actor_membership, Capability.WORKSPACE_MANAGE_INVITATIONS):
        raise InsufficientRoleError("You do not have permission to manage invitations.")
    if invitation.tenant_id != actor_membership.tenant_id:
        raise TenancyError("Invitation does not belong to this workspace.")
    invitation.status = InvitationStatus.REVOKED
    invitation.save(update_fields=["status", "updated_at"])
    return invitation
