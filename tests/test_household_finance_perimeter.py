"""Member visibility, enforced where the user actually looks.

Phase 3 built the visibility machinery and enforced it in the household
analytics — and nowhere else. A "private" account was private on the summary
page and fully visible in the accounts list, the transactions ledger, and every
lookup by id. These tests drive the *finance* endpoints, because that is the
surface the feature was always about.

The read rule under test: an account the member may not see behaves exactly
like an account that does not exist. Same 404, same "not found", including as a
transfer leg. Anything softer — a 403, a redacted row — confirms the account
exists, which is the leak.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.household.models import SharingPolicy
from apps.tenancy.models import Membership, Role, Tenant, TenantType
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

FINANCE = "/api/v1/finance"
HOUSEHOLD = "/api/v1/household"


def _client(user, tenant_id):
    client = APIClient()
    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_TENANT_ID=str(tenant_id))
    return client


@pytest.fixture
def household():
    """Boro holds a private account with a transaction in it; Ama is the
    workspace owner and must not see either."""
    tenant = Tenant.objects.create(name="The Otienos", type=TenantType.HOUSEHOLD)
    ama, boro = UserFactory(), UserFactory()
    Membership.objects.create(tenant=tenant, user=ama, role=Role.OWNER)
    Membership.objects.create(tenant=tenant, user=boro, role=Role.MEMBER)
    ama_client, boro_client = _client(ama, tenant.id), _client(boro, tenant.id)

    account = boro_client.post(
        f"{FINANCE}/accounts/",
        {
            "name": "Boro private",
            "account_type": "savings",
            "currency": "KES",
            "opening_balance_minor": 500_000,
        },
        format="json",
    ).data
    category = boro_client.post(
        f"{FINANCE}/categories/",
        {"name": "Groceries", "kind": "expense", "currency": "KES"},
        format="json",
    ).data
    txn = boro_client.post(
        f"{FINANCE}/transactions/",
        {
            "type": "expense",
            "financial_account_id": account["id"],
            "category_id": category["id"],
            "amount_minor": 12_345,
            "occurred_at": "2026-07-10T12:00:00Z",
        },
        format="json",
    ).data
    boro_client.put(f"{HOUSEHOLD}/sharing/{account['id']}/", {"policy": SharingPolicy.PRIVATE}, format="json")
    return {
        "tenant": tenant,
        "ama_client": ama_client,
        "boro_client": boro_client,
        "account": account,
        "txn": txn,
        "category": category,
    }


# ---------------------------------------------------------------------------
# reads: invisible == nonexistent
# ---------------------------------------------------------------------------


def test_a_private_account_is_absent_from_the_accounts_endpoint(household):
    listed = household["ama_client"].get(f"{FINANCE}/accounts/").data
    assert household["account"]["id"] not in {a["id"] for a in listed}
    # ...and still there for its owner.
    own = household["boro_client"].get(f"{FINANCE}/accounts/").data
    assert household["account"]["id"] in {a["id"] for a in own}


def test_a_private_account_404s_by_id_exactly_like_a_nonexistent_one(household):
    account_id = household["account"]["id"]
    real = household["ama_client"].get(f"{FINANCE}/accounts/{account_id}/statement/")
    fake = household["ama_client"].get(f"{FINANCE}/accounts/00000000-0000-0000-0000-000000000000/statement/")
    # The pair must be indistinguishable — a different status would confirm
    # the account exists.
    assert real.status_code == fake.status_code == 404


def test_a_private_accounts_transactions_are_absent_from_the_ledger(household):
    page = household["ama_client"].get(f"{FINANCE}/transactions/").data
    ids = {t["id"] for t in page["results"]}
    assert household["txn"]["id"] not in ids


def test_a_private_accounts_transaction_404s_by_id(household):
    res = household["ama_client"].get(f"{FINANCE}/transactions/{household['txn']['id']}/")
    assert res.status_code == 404
    # The owner still reaches it.
    assert (
        household["boro_client"].get(f"{FINANCE}/transactions/{household['txn']['id']}/").status_code == 200
    )


def test_a_private_account_cannot_be_a_transfer_destination(household):
    """Sending money *to* an account you cannot see would confirm it exists —
    and the sender could not see the money again anyway."""
    mine = (
        household["ama_client"]
        .post(
            f"{FINANCE}/accounts/",
            {
                "name": "Ama current",
                "account_type": "checking",
                "currency": "KES",
                "opening_balance_minor": 300_000,
            },
            format="json",
        )
        .data
    )
    res = household["ama_client"].post(
        f"{FINANCE}/transfers/",
        {
            "from_account_id": mine["id"],
            "to_account_id": household["account"]["id"],
            "amount_minor": 1_000,
            "occurred_at": "2026-08-01T12:00:00Z",
        },
        format="json",
    )
    assert res.status_code == 400
    assert "not found" in res.data["detail"]


# ---------------------------------------------------------------------------
# writes: visible but protected
# ---------------------------------------------------------------------------


@pytest.fixture
def read_only_account(household):
    account = (
        household["boro_client"]
        .post(
            f"{FINANCE}/accounts/",
            {
                "name": "Boro salary",
                "account_type": "checking",
                "currency": "KES",
                "opening_balance_minor": 800_000,
            },
            format="json",
        )
        .data
    )
    household["boro_client"].put(
        f"{HOUSEHOLD}/sharing/{account['id']}/", {"policy": SharingPolicy.READ_ONLY}, format="json"
    )
    return account


def test_a_read_only_account_is_visible_but_rejects_a_partners_edit(household, read_only_account):
    listed = household["ama_client"].get(f"{FINANCE}/accounts/").data
    assert read_only_account["id"] in {a["id"] for a in listed}

    res = household["ama_client"].patch(
        f"{FINANCE}/accounts/{read_only_account['id']}/", {"name": "Renamed"}, format="json"
    )
    assert res.status_code == 403
    assert "read-only" in res.data["detail"]


def test_a_partner_cannot_record_spending_on_a_read_only_account(household, read_only_account):
    res = household["ama_client"].post(
        f"{FINANCE}/transactions/",
        {
            "type": "expense",
            "financial_account_id": read_only_account["id"],
            "category_id": household["category"]["id"],
            "amount_minor": 5_000,
            "occurred_at": "2026-08-01T12:00:00Z",
        },
        format="json",
    )
    assert res.status_code == 403


def test_a_transfer_out_of_a_read_only_account_is_refused(household, read_only_account):
    mine = (
        household["ama_client"]
        .post(
            f"{FINANCE}/accounts/",
            {"name": "Ama current", "account_type": "checking", "currency": "KES"},
            format="json",
        )
        .data
    )
    res = household["ama_client"].post(
        f"{FINANCE}/transfers/",
        {
            "from_account_id": read_only_account["id"],
            "to_account_id": mine["id"],
            "amount_minor": 1_000,
            "occurred_at": "2026-08-01T12:00:00Z",
        },
        format="json",
    )
    assert res.status_code == 403


def test_an_approval_required_edit_points_at_the_change_request_flow(household):
    account = (
        household["boro_client"]
        .post(
            f"{FINANCE}/accounts/",
            {"name": "Boro fund", "account_type": "savings", "currency": "KES"},
            format="json",
        )
        .data
    )
    household["boro_client"].put(
        f"{HOUSEHOLD}/sharing/{account['id']}/",
        {"policy": SharingPolicy.APPROVAL_REQUIRED},
        format="json",
    )
    res = household["ama_client"].patch(
        f"{FINANCE}/accounts/{account['id']}/", {"name": "Renamed"}, format="json"
    )
    assert res.status_code == 403
    assert "change-request" in res.data["detail"]


def test_the_owner_still_edits_their_protected_account_freely(household, read_only_account):
    res = household["boro_client"].patch(
        f"{FINANCE}/accounts/{read_only_account['id']}/", {"name": "Still mine"}, format="json"
    )
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# the single-member workspace stays untouched
# ---------------------------------------------------------------------------


def test_a_personal_workspace_sees_no_change_at_all():
    """The perimeter must be inert until a second person joins — and it must
    stay inert even though other workspaces exist on the platform."""
    tenant = Tenant.objects.create(name="Solo", type=TenantType.PERSONAL)
    user = UserFactory()
    Membership.objects.create(tenant=tenant, user=user, role=Role.OWNER)
    # Noise: other tenants' memberships exist.
    other = Tenant.objects.create(name="Elsewhere", type=TenantType.HOUSEHOLD)
    Membership.objects.create(tenant=other, user=UserFactory(), role=Role.OWNER)

    client = _client(user, tenant.id)
    account = client.post(
        f"{FINANCE}/accounts/",
        {"name": "Mine", "account_type": "checking", "currency": "USD"},
        format="json",
    ).data
    assert account["id"] in {a["id"] for a in client.get(f"{FINANCE}/accounts/").data}
    assert (
        client.patch(f"{FINANCE}/accounts/{account['id']}/", {"name": "Renamed"}, format="json").status_code
        == 200
    )
