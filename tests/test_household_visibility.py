"""Member-level visibility: the boundary with no database backstop.

The tenant boundary is enforced twice — in Python and by row-level security —
so a missed check is survivable. This one is enforced once, in Python, because
RLS binds a tenant and two partners share a tenant. Everything keeping one
partner's private account away from the other is in `visibility.py`, so these
tests are the only thing standing behind it.

They therefore check for a leak the three different ways it shows up: in a
listing, in a lookup by id, and in an aggregate figure. A filter that is right
about the first and wrong about the third still discloses the balance.
"""

from __future__ import annotations

import uuid

import pytest

from apps.finance import services as finance_services
from apps.finance.models import AccountType, FinancialAccount
from apps.household import visibility
from apps.household.models import AccountSharing, SharingPolicy
from apps.tenancy.models import Membership, Role, Tenant, TenantType
from tests.factories import UserFactory
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def household():
    """A workspace with two members: Ama and her partner Boro."""
    tenant = Tenant.objects.create(name="The Otienos", type=TenantType.HOUSEHOLD)
    ama = UserFactory()
    boro = UserFactory()
    ama_m = Membership.objects.create(tenant=tenant, user=ama, role=Role.OWNER)
    boro_m = Membership.objects.create(tenant=tenant, user=boro, role=Role.MEMBER)
    return tenant, ama, boro, ama_m, boro_m


def _account(name: str) -> FinancialAccount:
    return finance_services.create_financial_account(
        name=name, account_type=AccountType.CHECKING, currency="KES", opening_balance_minor=100_000
    )


# ---------------------------------------------------------------------------
# the single-member case must stay inert
# ---------------------------------------------------------------------------


def test_a_one_person_workspace_is_unaffected():
    """Without this, shipping the phase would make every existing single-user
    workspace's accounts vanish. The change has to be inert until a second
    person actually joins."""
    tenant = Tenant.objects.create(name="Just me", type=TenantType.PERSONAL)
    user = UserFactory()
    Membership.objects.create(tenant=tenant, user=user, role=Role.OWNER)

    with tenant_scope(tenant.id, actor_id=user.id):
        account = _account("Current")
        AccountSharing.objects.create(financial_account=account, policy=SharingPolicy.PRIVATE, owner=None)
        assert visibility.visible_account_ids() is None
        assert visibility.restrict_accounts(FinancialAccount.objects.all()).count() == 1
        assert visibility.can_write_account(account.id)


def test_a_household_type_workspace_with_one_member_still_behaves_as_personal():
    """Counted, not inferred from the tenant's label: the type is something
    somebody chose, the member count is the fact."""
    tenant = Tenant.objects.create(name="Household of one", type=TenantType.HOUSEHOLD)
    user = UserFactory()
    Membership.objects.create(tenant=tenant, user=user, role=Role.OWNER)
    with tenant_scope(tenant.id, actor_id=user.id):
        assert visibility.is_single_member_workspace()
        assert visibility.visible_account_ids() is None


# ---------------------------------------------------------------------------
# the leak, checked three ways
# ---------------------------------------------------------------------------


def test_a_private_account_is_absent_from_a_partners_listing(household):
    tenant, ama, boro, ama_m, _ = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        secret = _account("Ama's own")
        AccountSharing.objects.create(financial_account=secret, policy=SharingPolicy.PRIVATE, owner=ama_m)

    with tenant_scope(tenant.id, actor_id=boro.id):
        visible = visibility.restrict_accounts(FinancialAccount.objects.all())
        assert secret.id not in {a.id for a in visible}


def test_a_private_account_cannot_be_reached_by_id(household):
    """A filter right about listings and wrong about lookups still leaks —
    ids are guessable from a URL somebody was shown once."""
    tenant, ama, boro, ama_m, _ = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        secret = _account("Ama's own")
        AccountSharing.objects.create(financial_account=secret, policy=SharingPolicy.PRIVATE, owner=ama_m)

    with tenant_scope(tenant.id, actor_id=boro.id):
        found = visibility.restrict_accounts(FinancialAccount.objects.filter(id=secret.id)).first()
        assert found is None


def test_a_private_account_is_excluded_from_what_a_partner_can_itemise(household):
    """The third shape of the same leak: not the row, the number."""
    tenant, ama, boro, ama_m, _ = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        secret = _account("Ama's own")
        AccountSharing.objects.create(financial_account=secret, policy=SharingPolicy.PRIVATE, owner=ama_m)
        joint = _account("Joint")
        AccountSharing.objects.create(financial_account=joint, policy=SharingPolicy.SHARED, is_joint=True)

    with tenant_scope(tenant.id, actor_id=boro.id):
        allowed = visibility.visible_account_ids()
        assert joint.id in allowed
        assert secret.id not in allowed


def test_the_owner_always_sees_their_own_private_account(household):
    tenant, ama, _boro, ama_m, _ = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        secret = _account("Ama's own")
        AccountSharing.objects.create(financial_account=secret, policy=SharingPolicy.PRIVATE, owner=ama_m)
        assert secret.id in visibility.visible_account_ids()


# ---------------------------------------------------------------------------
# the four policies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "policy,visible,writable",
    [
        (SharingPolicy.PRIVATE, False, False),
        (SharingPolicy.SHARED, True, True),
        (SharingPolicy.READ_ONLY, True, False),
        (SharingPolicy.APPROVAL_REQUIRED, True, False),
    ],
)
def test_each_policy_means_what_it_says(household, policy, visible, writable):
    tenant, ama, boro, ama_m, _ = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        account = _account(f"Ama {policy}")
        AccountSharing.objects.create(financial_account=account, policy=policy, owner=ama_m)

    with tenant_scope(tenant.id, actor_id=boro.id):
        allowed = visibility.visible_account_ids()
        assert (account.id in allowed) is visible
        assert visibility.can_write_account(account.id) is writable


def test_approval_required_routes_a_partners_change_into_a_request(household):
    tenant, ama, boro, ama_m, _ = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        account = _account("Ama's savings")
        AccountSharing.objects.create(
            financial_account=account, policy=SharingPolicy.APPROVAL_REQUIRED, owner=ama_m
        )

    with tenant_scope(tenant.id, actor_id=boro.id):
        assert visibility.needs_approval(account.id)
    with tenant_scope(tenant.id, actor_id=ama.id):
        # ...but not the owner's own change.
        assert not visibility.needs_approval(account.id)


def test_a_joint_account_is_visible_and_writable_by_both(household):
    tenant, ama, boro, _ama_m, _ = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        joint = _account("Joint current")
        AccountSharing.objects.create(
            financial_account=joint, policy=SharingPolicy.PRIVATE, is_joint=True, owner=None
        )

    for user in (ama, boro):
        with tenant_scope(tenant.id, actor_id=user.id):
            assert joint.id in visibility.visible_account_ids()
            assert visibility.can_write_account(joint.id)


# ---------------------------------------------------------------------------
# failing closed
# ---------------------------------------------------------------------------


def test_an_unknown_actor_gets_only_what_is_shared_not_everything(household):
    """A Celery task or a misconfigured view has no actor. The safe reading of
    "we do not know who is asking" is "assume the least", not "assume God"."""
    tenant, ama, _boro, ama_m, _ = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        secret = _account("Ama's own")
        AccountSharing.objects.create(financial_account=secret, policy=SharingPolicy.PRIVATE, owner=ama_m)
        shared = _account("Joint")
        AccountSharing.objects.create(financial_account=shared, policy=SharingPolicy.SHARED)

    # Bound tenant, no actor.
    with tenant_scope(tenant.id):
        allowed = visibility.visible_account_ids()
        assert shared.id in allowed
        assert secret.id not in allowed


def test_the_escape_hatch_is_explicit_and_greppable(household):
    """Household aggregates legitimately include accounts the viewer cannot
    itemise — but that has to be asked for by name."""
    tenant, ama, boro, ama_m, _ = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        secret = _account("Ama's own")
        AccountSharing.objects.create(financial_account=secret, policy=SharingPolicy.PRIVATE, owner=ama_m)

    with tenant_scope(tenant.id, actor_id=boro.id):
        assert secret.id not in visibility.visible_account_ids()
        assert secret.id in visibility.all_account_ids()


# ---------------------------------------------------------------------------
# accounts that predate the feature
# ---------------------------------------------------------------------------


def test_an_account_with_no_policy_stays_visible_rather_than_vanishing(household):
    """The one place this deliberately fails open. Silently hiding data a
    household already relies on is a worse failure than showing an account
    whose policy nobody has set yet."""
    tenant, ama, boro, _ama_m, _ = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        legacy = _account("Opened before this feature")

    with tenant_scope(tenant.id, actor_id=boro.id):
        assert legacy.id in visibility.visible_account_ids()


def test_the_backfill_registers_every_account_and_is_idempotent(household):
    tenant, ama, _boro, _ama_m, _ = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        _account("One")
        _account("Two")
        assert visibility.ensure_sharing_rows() == 2
        assert visibility.ensure_sharing_rows() == 0
        assert AccountSharing.objects.count() == 2


def test_the_backfill_does_not_guess_an_owner(household):
    """At backfill time we do not know who owns what, and guessing would assign
    somebody's account to their partner."""
    tenant, ama, _boro, _ama_m, _ = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        _account("Whose is this?")
        visibility.ensure_sharing_rows()
        assert AccountSharing.objects.get().owner_id is None


# ---------------------------------------------------------------------------
# the tenant boundary still holds underneath
# ---------------------------------------------------------------------------


def test_sharing_rows_do_not_leak_across_tenants(household):
    tenant, ama, _boro, ama_m, _ = household
    with tenant_scope(tenant.id, actor_id=ama.id):
        account = _account("Ours")
        AccountSharing.objects.create(financial_account=account, policy=SharingPolicy.SHARED)

    with tenant_scope(uuid.uuid4()):
        assert AccountSharing.objects.count() == 0
