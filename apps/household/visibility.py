"""One place that decides what a household member may see.

The tenant boundary is enforced twice — by `TenantScopedManager` in Python and
by row-level security in PostgreSQL — so forgetting it in application code is
survivable. The *member* boundary has no database backstop: RLS binds a tenant,
not a person, and two partners share a tenant. Everything protecting one
partner's private account from the other therefore lives here, in Python.

That asymmetry is the reason this module is written the way it is:

**One filter, used everywhere.** `visible_account_ids()` is the only sanctioned
answer to "which accounts may the current actor see". Call sites do not
assemble their own predicate, because a predicate assembled twice is a
predicate that will differ once.

**Fail closed on an unknown actor.** With no actor bound — a Celery task, a
management command, a misconfigured view — the answer is *not* "everything". It
is "only what is joint or explicitly shared", which is the safe reading of "we
do not know who is asking". Code that legitimately needs the whole workspace
asks for it by name via `all_account_ids()`, which is greppable.

**Personal workspaces are unaffected.** A workspace with one member has nothing
to hide from itself, and every account in it resolves as visible regardless of
policy. Without that, adding this phase would have made every existing
single-user workspace's accounts vanish — the change has to be inert until a
second person actually joins.
"""

from __future__ import annotations

import uuid

from django.db.models import Q, QuerySet

from apps.common.tenant_context import get_current_actor_id, require_current_tenant_id
from apps.tenancy.models import Membership

from .models import (
    VISIBLE_TO_HOUSEHOLD,
    WRITABLE_BY_HOUSEHOLD,
    AccountSharing,
    SharingPolicy,
)


def current_membership() -> Membership | None:
    """The acting member **of the ambient tenant**, or None.

    None is not an error: background work runs without an actor, and the
    callers below treat that as "assume the least".

    The tenant filter is load-bearing, not belt-and-braces. `Membership` is
    deliberately exempt from the tenant-scoped manager and from RLS — a user
    has to find their workspaces before any tenant is bound — so a bare
    `.filter(user_id=...)` returns rows from *every* workspace the user
    belongs to, and `.first()` picks one arbitrarily. Ownership comparisons
    made against the wrong workspace's membership id made a member's own
    private accounts invisible to them, which is how this line got its test.
    """
    actor_id = get_current_actor_id()
    if actor_id is None:
        return None
    return Membership.objects.filter(user_id=actor_id, tenant_id=require_current_tenant_id()).first()


def is_single_member_workspace() -> bool:
    """A workspace nobody shares has nothing to hide from itself.

    Counted rather than inferred from the tenant's `type`, because the type is
    a label somebody chose and the member count is the fact. A "household"
    workspace with one member behaves as personal until the partner joins,
    which is exactly the adoption path this has to survive.

    Counted **within the ambient tenant** — see `current_membership` for why
    that has to be said out loud. An unscoped count here counted the entire
    platform's memberships, which made every personal workspace on any real
    deployment look shared and switched member filtering on for all of them.
    """
    return Membership.objects.filter(tenant_id=require_current_tenant_id()).count() <= 1


def visible_account_ids() -> set[uuid.UUID] | None:
    """Financial account ids the current actor may see, or None for "all".

    `None` means no restriction applies — a single-member workspace — and is
    distinct from an empty set, which means "this person may see nothing".
    Conflating the two is the bug this return type exists to prevent.
    """
    if is_single_member_workspace():
        return None

    membership = current_membership()
    shared = Q(is_joint=True) | Q(policy__in=VISIBLE_TO_HOUSEHOLD)
    if membership is not None:
        # Your own accounts are always yours to see, whatever the policy says.
        shared |= Q(owner_id=membership.id)

    return (
        set(AccountSharing.objects.filter(shared).values_list("financial_account_id", flat=True))
        | _unregistered_account_ids()
    )


def _unregistered_account_ids() -> set[uuid.UUID]:
    """Accounts with no `AccountSharing` row at all.

    These are accounts that predate this feature, or were created by a path
    that has not been taught about sharing yet. They are treated as *visible*.

    That is the one place this module deliberately fails open, and it is a
    considered trade: the alternative is that shipping this phase makes every
    existing account in every existing multi-member workspace disappear at
    once. Silently hiding data a household already relies on is a worse failure
    than showing an account whose policy nobody has set — and the fix is a
    backfill, which `ensure_sharing_rows()` performs, not a different rule.
    """
    from apps.finance.models import FinancialAccount

    registered = set(AccountSharing.objects.values_list("financial_account_id", flat=True))
    everything = set(FinancialAccount.objects.values_list("id", flat=True))
    return everything - registered


def all_account_ids() -> set[uuid.UUID]:
    """Every account in the workspace, ignoring member visibility.

    The explicit, greppable escape hatch — the same role `UnscopedManager`
    plays for tenancy. Used by household *aggregates*, where the household's
    combined net worth legitimately includes accounts the viewer cannot itemise.
    """
    from apps.finance.models import FinancialAccount

    return set(FinancialAccount.objects.values_list("id", flat=True))


def restrict_accounts(queryset: QuerySet) -> QuerySet:
    """Narrow a `FinancialAccount` queryset to what the actor may see."""
    allowed = visible_account_ids()
    if allowed is None:
        return queryset
    return queryset.filter(id__in=allowed)


def can_write_account(account_id: uuid.UUID) -> bool:
    """Whether the actor may change this account directly.

    An owner always can. Everyone else can only when the policy says so —
    `READ_ONLY` and `APPROVAL_REQUIRED` both answer False here, and the second
    of those is what routes a change into `ChangeRequest` instead of applying it.
    """
    if is_single_member_workspace():
        return True
    sharing = AccountSharing.objects.filter(financial_account_id=account_id).first()
    if sharing is None:
        return True  # unregistered: see `_unregistered_account_ids`
    membership = current_membership()
    if membership is not None and sharing.owner_id == membership.id:
        return True
    return sharing.is_joint or sharing.policy in WRITABLE_BY_HOUSEHOLD


def needs_approval(account_id: uuid.UUID) -> bool:
    """Whether a non-owner's change should become a request rather than a write."""
    if is_single_member_workspace():
        return False
    sharing = AccountSharing.objects.filter(financial_account_id=account_id).first()
    if sharing is None:
        return False
    membership = current_membership()
    if membership is not None and sharing.owner_id == membership.id:
        return False
    return sharing.policy == SharingPolicy.APPROVAL_REQUIRED


def ensure_sharing_rows(*, default_policy: str | None = None) -> int:
    """Give every account a sharing row, so nothing relies on the fail-open path.

    Idempotent. Returns how many rows it created. Called when a second member
    joins a workspace — the moment the distinction starts to matter — rather
    than by a migration, because at migration time we do not know which member
    owns what and guessing would assign somebody's account to their partner.
    """
    from apps.finance.models import FinancialAccount

    policy = default_policy or SharingPolicy.SHARED
    registered = set(AccountSharing.objects.values_list("financial_account_id", flat=True))
    created = 0
    for account in FinancialAccount.objects.exclude(id__in=registered):
        AccountSharing.objects.create(financial_account=account, policy=policy, is_joint=False, owner=None)
        created += 1
    return created
