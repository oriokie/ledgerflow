"""Approval requests: the mechanism that gives `APPROVAL_REQUIRED` its teeth.

Before this, the policy had a check and nothing to route into, so it behaved as
read-only. The properties worth defending are the ones that decide whether an
approval flow is real or theatre:

* approving *applies* the change — otherwise it was only ever a message,
* only the owner can approve, whatever anyone's role in the workspace is,
* a request can never move money,
* a request that did not need to be one is refused, because a cluttered queue
  teaches people to approve without reading,
* the payload is re-validated at approval time, not trusted from when it was
  filed.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.finance.models import FinancialAccount
from apps.household import change_requests
from apps.household.models import AccountSharing, ChangeRequest, SharingPolicy
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
    """Ama owns the workspace. Boro owns an account under approval."""
    tenant = Tenant.objects.create(name="The Otienos", type=TenantType.HOUSEHOLD)
    ama, boro = UserFactory(), UserFactory()
    ama_m = Membership.objects.create(tenant=tenant, user=ama, role=Role.OWNER)
    boro_m = Membership.objects.create(tenant=tenant, user=boro, role=Role.MEMBER)
    ama_client, boro_client = _client(ama, tenant.id), _client(boro, tenant.id)

    account = boro_client.post(
        "/api/v1/finance/accounts/",
        {
            "name": "Boro savings",
            "account_type": "savings",
            "currency": "KES",
            "opening_balance_minor": 500_000,
        },
        format="json",
    ).data
    boro_client.put(
        f"{BASE}/sharing/{account['id']}/",
        {"policy": SharingPolicy.APPROVAL_REQUIRED},
        format="json",
    )
    return {
        "tenant": tenant,
        "ama": ama,
        "boro": boro,
        "ama_m": ama_m,
        "boro_m": boro_m,
        "ama_client": ama_client,
        "boro_client": boro_client,
        "account": account,
    }


def _ask(client, account_id, payload, summary=""):
    return client.post(
        f"{BASE}/change-requests/",
        {"financial_account_id": account_id, "payload": payload, "summary": summary},
        format="json",
    )


# ---------------------------------------------------------------------------
# the happy path
# ---------------------------------------------------------------------------


def test_a_partner_can_propose_a_change(household):
    res = _ask(household["ama_client"], household["account"]["id"], {"name": "Joint savings"})
    assert res.status_code == 201
    assert res.data["status"] == "pending"
    assert res.data["payload"] == {"name": "Joint savings"}


def test_the_summary_reads_in_the_owners_terms(household):
    res = _ask(household["ama_client"], household["account"]["id"], {"policy": "shared"})
    assert "Shared with the household" in res.data["summary"]


def test_approving_actually_applies_the_change(household):
    """Otherwise the owner has to make the change by hand and the request was
    only ever a message."""
    created = _ask(household["ama_client"], household["account"]["id"], {"name": "Rainy day"}).data

    res = household["boro_client"].post(f"{BASE}/change-requests/{created['id']}/approve/", {}, format="json")
    assert res.status_code == 200
    assert res.data["status"] == "approved"
    assert res.data["applied"]["name"]["after"] == "Rainy day"

    with tenant_scope(household["tenant"].id):
        assert FinancialAccount.objects.get(id=household["account"]["id"]).name == "Rainy day"


def test_a_sharing_change_can_be_requested_and_applied(household):
    created = _ask(
        household["ama_client"], household["account"]["id"], {"policy": "shared", "is_joint": True}
    ).data
    household["boro_client"].post(f"{BASE}/change-requests/{created['id']}/approve/", {}, format="json")
    with tenant_scope(household["tenant"].id):
        sharing = AccountSharing.objects.get(financial_account_id=household["account"]["id"])
    assert sharing.policy == "shared"
    assert sharing.is_joint is True


def test_declining_leaves_the_account_alone_but_keeps_the_record(household):
    """The value of the apparatus is the record, and one that can be tidied
    away is worth less than no record."""
    created = _ask(household["ama_client"], household["account"]["id"], {"name": "Nope"}).data

    res = household["boro_client"].post(f"{BASE}/change-requests/{created['id']}/decline/", {}, format="json")
    assert res.status_code == 200
    assert res.data["status"] == "declined"
    assert res.data["resolved_by_id"] == str(household["boro"].id)

    with tenant_scope(household["tenant"].id):
        assert FinancialAccount.objects.get(id=household["account"]["id"]).name == "Boro savings"
        assert ChangeRequest.objects.count() == 1


# ---------------------------------------------------------------------------
# who may approve
# ---------------------------------------------------------------------------


def test_the_requester_cannot_approve_their_own_request(household):
    """Ama is the workspace OWNER — the most senior role — and it makes no
    difference. An approval a senior role can grant itself is not an approval."""
    created = _ask(household["ama_client"], household["account"]["id"], {"name": "Mine now"}).data

    res = household["ama_client"].post(f"{BASE}/change-requests/{created['id']}/approve/", {}, format="json")
    assert res.status_code == 403
    assert "Only the account's owner" in res.data["detail"]

    with tenant_scope(household["tenant"].id):
        assert FinancialAccount.objects.get(id=household["account"]["id"]).name == "Boro savings"


def test_a_third_member_cannot_see_or_resolve_the_request(household):
    """An approval queue is not a noticeboard."""
    created = _ask(household["ama_client"], household["account"]["id"], {"name": "X"}).data

    third = UserFactory()
    Membership.objects.create(tenant=household["tenant"], user=third, role=Role.ADMIN)
    third_client = _client(third, household["tenant"].id)

    assert third_client.get(f"{BASE}/change-requests/").data["results"] == []
    assert (
        third_client.post(f"{BASE}/change-requests/{created['id']}/approve/", {}, format="json").status_code
        == 404
    )


def test_both_the_owner_and_the_requester_see_it(household):
    _ask(household["ama_client"], household["account"]["id"], {"name": "X"})
    assert len(household["ama_client"].get(f"{BASE}/change-requests/").data["results"]) == 1
    assert len(household["boro_client"].get(f"{BASE}/change-requests/").data["results"]) == 1


def test_a_resolved_request_cannot_be_resolved_again(household):
    created = _ask(household["ama_client"], household["account"]["id"], {"name": "X"}).data
    household["boro_client"].post(f"{BASE}/change-requests/{created['id']}/decline/", {}, format="json")
    res = household["boro_client"].post(f"{BASE}/change-requests/{created['id']}/approve/", {}, format="json")
    assert res.status_code == 403
    assert "already declined" in res.data["detail"]


# ---------------------------------------------------------------------------
# what may be requested
# ---------------------------------------------------------------------------


def test_a_request_can_never_move_money(household):
    """The allow-list is the boundary. Balances, currency and account type are
    absent on purpose."""
    for forbidden in (
        {"opening_balance_minor": 999},
        {"currency": "USD"},
        {"account_type": "checking"},
        {"ledger_account": "anything"},
    ):
        res = _ask(household["ama_client"], household["account"]["id"], forbidden)
        assert res.status_code == 400, forbidden
        assert "cannot be changed by request" in res.data["detail"]


def test_unknown_keys_are_rejected_rather_than_dropped(household):
    """Elsewhere unknown keys are silently discarded because the author is a
    model. Here the author is a person waiting to hear back, and quietly
    ignoring half their request then reporting it approved is worse than an
    error."""
    res = _ask(household["ama_client"], household["account"]["id"], {"name": "Fine", "nonsense": 1})
    assert res.status_code == 400
    assert "nonsense" in res.data["detail"]


def test_an_empty_request_is_refused(household):
    res = _ask(household["ama_client"], household["account"]["id"], {})
    assert res.status_code == 400


def test_a_bad_policy_value_is_refused(household):
    res = _ask(household["ama_client"], household["account"]["id"], {"policy": "everyone"})
    assert res.status_code == 400


def test_wrong_types_are_refused(household):
    assert _ask(household["ama_client"], household["account"]["id"], {"is_joint": "yes"}).status_code == 400
    assert _ask(household["ama_client"], household["account"]["id"], {"name": 42}).status_code == 400


def test_the_payload_is_revalidated_at_approval_not_trusted_from_filing(household):
    """A request can sit for weeks and the allow-list may narrow in between.
    Applying a field the product no longer considers requestable, because it
    was permitted when the request was filed, is quiet privilege escalation."""
    created = _ask(household["ama_client"], household["account"]["id"], {"name": "X"}).data

    with tenant_scope(household["tenant"].id, actor_id=household["boro"].id):
        stored = ChangeRequest.objects.get(id=created["id"])
        # Something slipped into the payload after it was filed.
        stored.payload = {"currency": "USD"}
        stored.save(update_fields=["payload"])

        with pytest.raises(change_requests.ChangeRequestError, match="cannot be changed"):
            change_requests.approve(stored)


# ---------------------------------------------------------------------------
# requests that should not exist
# ---------------------------------------------------------------------------


def test_the_owner_is_told_to_just_change_it(household):
    res = _ask(household["boro_client"], household["account"]["id"], {"name": "Mine"})
    assert res.status_code == 400
    assert "change it directly" in res.data["detail"]


def test_a_shared_account_needs_no_request(household):
    """A queue full of requests that did not need to be requests teaches people
    to approve without reading."""
    shared = (
        household["boro_client"]
        .post(
            "/api/v1/finance/accounts/",
            {"name": "Joint", "account_type": "checking", "currency": "KES"},
            format="json",
        )
        .data
    )
    household["boro_client"].put(
        f"{BASE}/sharing/{shared['id']}/", {"policy": SharingPolicy.SHARED}, format="json"
    )
    res = _ask(household["ama_client"], shared["id"], {"name": "Ours"})
    assert res.status_code == 400
    assert "yourself" in res.data["detail"]


def test_a_read_only_account_says_to_ask_directly(household):
    read_only = (
        household["boro_client"]
        .post(
            "/api/v1/finance/accounts/",
            {"name": "Salary", "account_type": "checking", "currency": "KES"},
            format="json",
        )
        .data
    )
    household["boro_client"].put(
        f"{BASE}/sharing/{read_only['id']}/", {"policy": SharingPolicy.READ_ONLY}, format="json"
    )
    res = _ask(household["ama_client"], read_only["id"], {"name": "Ours"})
    assert res.status_code == 400
    assert "Ask them directly" in res.data["detail"]


def test_a_private_account_cannot_even_be_asked_about(household):
    """Otherwise the endpoint confirms that a private account exists, which is
    the leak the whole phase exists to prevent."""
    private = (
        household["boro_client"]
        .post(
            "/api/v1/finance/accounts/",
            {"name": "Secret", "account_type": "savings", "currency": "KES"},
            format="json",
        )
        .data
    )
    household["boro_client"].put(
        f"{BASE}/sharing/{private['id']}/", {"policy": SharingPolicy.PRIVATE}, format="json"
    )
    res = _ask(household["ama_client"], private["id"], {"name": "Ours"})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# isolation and auth
# ---------------------------------------------------------------------------


def test_change_requests_require_authentication():
    assert APIClient().get(f"{BASE}/change-requests/").status_code in (401, 403)


def test_change_requests_do_not_leak_across_tenants(household):
    _ask(household["ama_client"], household["account"]["id"], {"name": "X"})

    other_tenant = Tenant.objects.create(name="Elsewhere", type=TenantType.HOUSEHOLD)
    other = UserFactory()
    Membership.objects.create(tenant=other_tenant, user=other, role=Role.OWNER)
    assert _client(other, other_tenant.id).get(f"{BASE}/change-requests/").data["results"] == []


def test_the_queue_can_be_filtered_by_status(household):
    created = _ask(household["ama_client"], household["account"]["id"], {"name": "X"}).data
    household["boro_client"].post(f"{BASE}/change-requests/{created['id']}/decline/", {}, format="json")
    pending = household["ama_client"].get(f"{BASE}/change-requests/?status=pending").data["results"]
    declined = household["ama_client"].get(f"{BASE}/change-requests/?status=declined").data["results"]
    assert pending == []
    assert len(declined) == 1
