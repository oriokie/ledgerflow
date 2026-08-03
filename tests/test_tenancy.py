"""Tenancy + Row-Level-Security integration tests.

These hit real endpoints against a real Postgres test database (pytest-django
runs migrations, including the RLS policies, against it) — the isolation
guarantee is proven here, not assumed.
"""

from __future__ import annotations

import pytest

from tests.factories import MembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_create_workspace(auth_client, user):
    resp = auth_client.post(
        "/api/v1/tenancy/workspaces/",
        {
            "name": "My Household",
            "base_currency": "USD",
        },
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["role"] == "owner"
    assert resp.data["tenant"]["name"] == "My Household"


def test_list_workspaces_returns_only_my_memberships(auth_client, user):
    auth_client.post("/api/v1/tenancy/workspaces/", {"name": "Mine"}, format="json")
    MembershipFactory()  # someone else's workspace — must not appear

    resp = auth_client.get("/api/v1/tenancy/workspaces/")
    assert resp.status_code == 200
    assert len(resp.data) == 1
    assert resp.data[0]["tenant"]["name"] == "Mine"


def test_ledger_endpoint_requires_tenant_header(auth_client):
    resp = auth_client.get("/api/v1/ledger/accounts/")
    assert resp.status_code == 403
    assert resp.data["error"]["code"] == "permission_denied"


def test_non_member_cannot_access_workspace_ledger(auth_client, tenant_context):
    membership, _owner_client = tenant_context
    # `auth_client`'s user has no membership anywhere.
    resp = auth_client.get(
        "/api/v1/ledger/accounts/",
        HTTP_X_TENANT_ID=str(membership.tenant_id),
    )
    assert resp.status_code == 403


def test_rls_isolates_accounts_between_tenants(tenant_context):
    membership_a, client_a = tenant_context
    membership_b = MembershipFactory()
    from tests.conftest import _bearer_client

    client_b = _bearer_client(membership_b.user, tenant_id=membership_b.tenant_id)

    created = client_a.post(
        "/api/v1/ledger/accounts/",
        {
            "name": "Checking",
            "kind": "asset",
            "currency": "USD",
        },
        format="json",
    )
    assert created.status_code == 201

    tenant_a_view = client_a.get("/api/v1/ledger/accounts/")
    assert len(tenant_a_view.data) == 1

    tenant_b_view = client_b.get("/api/v1/ledger/accounts/")
    assert tenant_b_view.data == []  # RLS: zero leakage, not just an app-level filter


def test_members_endpoint_is_read_only_members_are_added_via_invitations(tenant_context):
    """Superseded by the invitation flow (see test_invitations.py):
    workspace membership now always goes through create_invitation ->
    accept_invitation, so a user can never be added to a workspace without
    their consent. `/workspaces/members/` is read-only."""
    membership, client = tenant_context
    target = UserFactory(email="viewer@example.com")
    resp = client.post(
        "/api/v1/tenancy/workspaces/members/",
        {"email": target.email, "role": "member"},
        format="json",
        HTTP_X_TENANT_ID=str(membership.tenant_id),
    )
    assert resp.status_code == 405
