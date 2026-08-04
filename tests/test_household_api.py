"""HTTP contract for the household API.

The one that matters most is `test_an_admin_cannot_expose_their_partners_account`.
Role seniority governs the workspace; it does not confer the right to expose
somebody else's finances, and a household where the person who set up billing
can un-private their partner's savings is not one either of them should trust.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.household.models import AccountSharing, SharingPolicy
from apps.tenancy.models import Membership, Role, Tenant, TenantType
from tests.factories import UserFactory
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db

BASE = "/api/v1/household"


def _client(user, tenant_id):
    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant_id))
    return client


@pytest.fixture
def household():
    """Ama owns the workspace; Boro is an ordinary member."""
    tenant = Tenant.objects.create(name="The Otienos", type=TenantType.HOUSEHOLD)
    ama, boro = UserFactory(), UserFactory()
    ama_m = Membership.objects.create(tenant=tenant, user=ama, role=Role.OWNER)
    boro_m = Membership.objects.create(tenant=tenant, user=boro, role=Role.MEMBER)
    return {
        "tenant": tenant,
        "ama": ama,
        "boro": boro,
        "ama_m": ama_m,
        "boro_m": boro_m,
        "ama_client": _client(ama, tenant.id),
        "boro_client": _client(boro, tenant.id),
    }


def _account(client, name="Savings"):
    return client.post(
        "/api/v1/finance/accounts/",
        {"name": name, "account_type": "savings", "currency": "KES", "opening_balance_minor": 500_000},
        format="json",
    ).data


# ---------------------------------------------------------------------------
# who may change a sharing policy
# ---------------------------------------------------------------------------


def test_an_owner_can_set_their_accounts_policy(household):
    client = household["boro_client"]
    account = _account(client, "Boro's savings")
    res = client.put(
        f"{BASE}/sharing/{account['id']}/",
        {"policy": SharingPolicy.PRIVATE},
        format="json",
    )
    assert res.status_code == 200
    assert res.data["policy"] == "private"
    assert res.data["owner_membership_id"] == str(household["boro_m"].id)


def test_an_admin_cannot_expose_their_partners_account(household):
    """The rule this app exists to enforce. Ama is the workspace OWNER — the
    most senior role there is — and still cannot change how Boro's account is
    shared."""
    boro_client = household["boro_client"]
    account = _account(boro_client, "Boro's savings")
    boro_client.put(f"{BASE}/sharing/{account['id']}/", {"policy": SharingPolicy.PRIVATE}, format="json")

    res = household["ama_client"].put(
        f"{BASE}/sharing/{account['id']}/", {"policy": SharingPolicy.SHARED}, format="json"
    )
    assert res.status_code in (403, 404)
    with tenant_scope(household["tenant"].id):
        assert AccountSharing.objects.get(financial_account_id=account["id"]).policy == "private"


def test_an_unowned_account_can_be_claimed(household):
    """How backfilled rows get adopted."""
    client = household["ama_client"]
    account = _account(client, "Legacy")
    with tenant_scope(household["tenant"].id):
        AccountSharing.objects.create(
            financial_account_id=account["id"], policy=SharingPolicy.SHARED, owner=None
        )
    res = client.put(f"{BASE}/sharing/{account['id']}/", {"policy": SharingPolicy.READ_ONLY}, format="json")
    assert res.status_code == 200
    assert res.data["owner_membership_id"] == str(household["ama_m"].id)


def test_a_private_account_is_not_discoverable_through_the_sharing_endpoint(household):
    """An unshared account must not become findable through the very endpoint
    that governs sharing."""
    boro_client = household["boro_client"]
    account = _account(boro_client, "Boro's savings")
    boro_client.put(f"{BASE}/sharing/{account['id']}/", {"policy": SharingPolicy.PRIVATE}, format="json")

    listed = household["ama_client"].get(f"{BASE}/sharing/").data["results"]
    assert account["id"] not in {row["financial_account_id"] for row in listed}


def test_setting_a_policy_on_an_invisible_account_is_a_404(household):
    boro_client = household["boro_client"]
    account = _account(boro_client, "Boro's savings")
    boro_client.put(f"{BASE}/sharing/{account['id']}/", {"policy": SharingPolicy.PRIVATE}, format="json")
    res = household["ama_client"].put(
        f"{BASE}/sharing/{account['id']}/", {"policy": SharingPolicy.SHARED}, format="json"
    )
    assert res.status_code in (403, 404)


# ---------------------------------------------------------------------------
# the summary
# ---------------------------------------------------------------------------


def test_the_summary_totals_include_what_the_caller_cannot_itemise(household):
    boro_client = household["boro_client"]
    private = _account(boro_client, "Boro's savings")
    boro_client.put(f"{BASE}/sharing/{private['id']}/", {"policy": SharingPolicy.PRIVATE}, format="json")

    res = household["ama_client"].get(f"{BASE}/summary/")
    assert res.status_code == 200
    position = res.data["position"]
    assert position["total_assets_minor"] > position["visible_assets_minor"]
    assert position["withheld_account_count"] == 1
    assert any("private to their owner" in n for n in position["notes"])


def test_the_summary_carries_coverage_and_the_expense_split(household):
    res = household["ama_client"].get(f"{BASE}/summary/")
    assert "coverage" in res.data
    assert "expense_split" in res.data
    assert res.data["expense_split"]["notes"]


# ---------------------------------------------------------------------------
# profiles and dependants
# ---------------------------------------------------------------------------


def test_a_member_edits_only_their_own_profile(household):
    """Editing a partner's stated relationship or agreed share is a claim about
    them, and should come from them — so there is no id in the path."""
    res = household["boro_client"].patch(
        f"{BASE}/members/",
        {"display_name": "Boro", "relationship": "partner", "contribution_share": "0.4000"},
        format="json",
    )
    assert res.status_code == 200
    assert res.data["membership_id"] == str(household["boro_m"].id)
    assert res.data["display_name"] == "Boro"


def test_a_contribution_share_can_be_cleared_back_to_not_agreed(household):
    client = household["ama_client"]
    client.patch(f"{BASE}/members/", {"contribution_share": "0.6000"}, format="json")
    res = client.patch(f"{BASE}/members/", {"contribution_share": None}, format="json")
    assert res.status_code == 200
    assert res.data["contribution_share"] is None


def test_dependants_round_trip(household):
    client = household["ama_client"]
    created = client.post(
        f"{BASE}/dependants/",
        {"name": "Kito", "relationship": "child", "monthly_cost_minor": 80_000, "support_until_year": 2044},
        format="json",
    )
    assert created.status_code == 201

    listed = client.get(f"{BASE}/dependants/").data["results"]
    assert [d["name"] for d in listed] == ["Kito"]

    patched = client.patch(
        f"{BASE}/dependants/{created.data['id']}/", {"monthly_cost_minor": 90_000}, format="json"
    )
    assert patched.data["monthly_cost_minor"] == 90_000

    assert client.delete(f"{BASE}/dependants/{created.data['id']}/").status_code == 204
    assert client.get(f"{BASE}/dependants/").data["results"] == []


def test_both_members_see_the_households_dependants(household):
    """A child is not a private fact between partners."""
    household["ama_client"].post(
        f"{BASE}/dependants/", {"name": "Kito", "relationship": "child"}, format="json"
    )
    listed = household["boro_client"].get(f"{BASE}/dependants/").data["results"]
    assert [d["name"] for d in listed] == ["Kito"]


# ---------------------------------------------------------------------------
# backfill
# ---------------------------------------------------------------------------


def test_the_backfill_registers_accounts_without_assigning_an_owner(household):
    client = household["ama_client"]
    _account(client, "One")
    _account(client, "Two")
    res = client.post(f"{BASE}/sharing/backfill/", {}, format="json")
    assert res.status_code == 200
    assert res.data["created"] == 2
    assert "for each member to claim" in res.data["detail"]
    with tenant_scope(household["tenant"].id):
        assert all(s.owner_id is None for s in AccountSharing.objects.all())


def test_the_backfill_needs_an_admin(household):
    """Boro is a MEMBER."""
    res = household["boro_client"].post(f"{BASE}/sharing/backfill/", {}, format="json")
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# isolation and auth
# ---------------------------------------------------------------------------


def test_the_household_api_requires_authentication():
    assert APIClient().get(f"{BASE}/summary/").status_code in (401, 403)


def test_another_workspace_sees_none_of_this_households_dependants(household):
    household["ama_client"].post(
        f"{BASE}/dependants/", {"name": "Kito", "relationship": "child"}, format="json"
    )
    other_tenant = Tenant.objects.create(name="Someone else", type=TenantType.HOUSEHOLD)
    other = UserFactory()
    Membership.objects.create(tenant=other_tenant, user=other, role=Role.OWNER)
    assert _client(other, other_tenant.id).get(f"{BASE}/dependants/").data["results"] == []
