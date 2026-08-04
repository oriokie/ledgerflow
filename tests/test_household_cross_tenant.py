"""Regression: household surfaces must not see other tenants' memberships.

`Membership` is deliberately exempt from both the tenant-scoped manager and
RLS — a user has to be able to find their workspaces before any tenant is
bound. Every other tenant-scoped table gets its isolation for free; queries
against Membership get nothing for free and must scope themselves.

The original Phase 3 code forgot that, three times over:

* `analytics.combined_position()` iterated `Membership.objects.all()` and so
  listed the members of *every workspace on the platform* — names derived from
  their email addresses — to anyone who opened `/household/summary/`;
* `visibility.is_single_member_workspace()` counted every membership in the
  database, so on any deployment with more than one user, every personal
  workspace was treated as shared;
* `visibility.current_membership()` took `.first()` of a user's memberships
  across all their workspaces, so ownership checks could be made against the
  wrong tenant's membership row.

None of it was caught because each test database held one tenant at a time.
This file exists to hold a second tenant in frame while the first is queried.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.finance import services as finance_services
from apps.finance.models import AccountType
from apps.household import analytics, visibility
from apps.household.models import AccountSharing, SharingPolicy
from apps.tenancy.models import Membership, Role, Tenant, TenantType
from tests.factories import UserFactory
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_worlds():
    """Two unrelated households, plus one user who belongs to both."""
    otienos = Tenant.objects.create(name="The Otienos", type=TenantType.HOUSEHOLD)
    ama, boro = UserFactory(), UserFactory()
    ama_m = Membership.objects.create(tenant=otienos, user=ama, role=Role.OWNER)
    Membership.objects.create(tenant=otienos, user=boro, role=Role.MEMBER)

    elsewhere = Tenant.objects.create(name="Elsewhere", type=TenantType.HOUSEHOLD)
    stranger = UserFactory()
    Membership.objects.create(tenant=elsewhere, user=stranger, role=Role.OWNER)
    # Ama also belongs to the other workspace — the case that breaks a naive
    # `.filter(user=...).first()`.
    ama_elsewhere = Membership.objects.create(tenant=elsewhere, user=ama, role=Role.MEMBER)

    return {
        "otienos": otienos,
        "elsewhere": elsewhere,
        "ama": ama,
        "boro": boro,
        "ama_m": ama_m,
        "ama_elsewhere": ama_elsewhere,
        "stranger": stranger,
    }


def _client(user, tenant_id):
    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant_id))
    return client


def test_the_member_list_stops_at_the_tenant_boundary(two_worlds):
    """The leak: a stranger's email-derived display name appearing in another
    household's member list."""
    with tenant_scope(two_worlds["otienos"].id, actor_id=two_worlds["ama"].id):
        position = analytics.combined_position()

    listed = {m.membership_id for m in position.members}
    assert str(two_worlds["ama_m"].id) in listed
    assert len(position.members) == 2  # Ama and Boro, nobody else
    stranger_name = two_worlds["stranger"].email.split("@")[0]
    assert all(stranger_name != m.display_name for m in position.members)


def test_the_members_endpoint_stops_at_the_tenant_boundary(two_worlds):
    client = _client(two_worlds["ama"], two_worlds["otienos"].id)
    results = client.get("/api/v1/household/members/").data["results"]
    assert len(results) == 2


def test_a_two_member_platform_does_not_make_a_personal_workspace_shared(two_worlds):
    """`is_single_member_workspace` must count this workspace's members, not
    the platform's. Otherwise every personal workspace on a real deployment is
    treated as shared and its accounts start getting filtered."""
    solo_tenant = Tenant.objects.create(name="Just me", type=TenantType.PERSONAL)
    solo = UserFactory()
    Membership.objects.create(tenant=solo_tenant, user=solo, role=Role.OWNER)

    # Plenty of other memberships exist on the platform (the fixture's four).
    with tenant_scope(solo_tenant.id, actor_id=solo.id):
        assert visibility.is_single_member_workspace()
        assert visibility.visible_account_ids() is None


def test_membership_resolution_picks_the_ambient_tenants_row(two_worlds):
    """Ama belongs to both workspaces. Inside the Otienos' workspace, her
    membership must resolve to the Otienos row — ownership comparisons made
    against the other workspace's membership id would make her own private
    accounts invisible to her."""
    with tenant_scope(two_worlds["otienos"].id, actor_id=two_worlds["ama"].id):
        membership = visibility.current_membership()
        assert membership is not None
        assert membership.id == two_worlds["ama_m"].id

    with tenant_scope(two_worlds["elsewhere"].id, actor_id=two_worlds["ama"].id):
        membership = visibility.current_membership()
        assert membership is not None
        assert membership.id == two_worlds["ama_elsewhere"].id


def test_a_private_account_stays_visible_to_its_owner_in_the_right_tenant(two_worlds):
    """The end-to-end consequence of wrong membership resolution: Ama's own
    private account vanishing from her because her ownership was checked
    against the other workspace's membership row."""
    with tenant_scope(two_worlds["otienos"].id, actor_id=two_worlds["ama"].id):
        account = finance_services.create_financial_account(
            name="Ama's own",
            account_type=AccountType.SAVINGS,
            currency="KES",
            opening_balance_minor=100_000,
        )
        AccountSharing.objects.create(
            financial_account=account,
            policy=SharingPolicy.PRIVATE,
            owner=two_worlds["ama_m"],
        )
        allowed = visibility.visible_account_ids()
        assert allowed is not None
        assert account.id in allowed


def test_the_expense_split_stops_at_the_tenant_boundary(two_worlds):
    with tenant_scope(two_worlds["otienos"].id, actor_id=two_worlds["ama"].id):
        split = analytics.expense_split()
    assert len(split.per_member) == 2
