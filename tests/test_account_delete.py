"""Per-user account deletion: password-gated, closes owned workspaces."""

from __future__ import annotations

import pytest

from apps.tenancy.models import Role
from tests.factories import MembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_delete_account_requires_the_password(tenant_context):
    _, client = tenant_context
    res = client.post("/api/v1/auth/me/delete/", {"password": "not-the-password"}, format="json")
    assert res.status_code == 400


def test_delete_account_closes_owned_workspaces_and_drops_the_email(tenant_context):
    membership, client = tenant_context
    user = membership.user
    original_email = user.email

    res = client.post(
        "/api/v1/auth/me/delete/",
        {"password": "correct-horse-battery-staple"},
        format="json",
    )
    assert res.status_code == 204, res.data

    user.refresh_from_db()
    membership.tenant.refresh_from_db()
    assert user.is_active is False
    assert user.is_verified is False
    assert user.email != original_email
    assert user.email.startswith("deleted+")
    assert membership.tenant.is_active is False


def test_delete_account_does_not_close_workspaces_the_user_does_not_own(tenant_context):
    owner_membership, _ = tenant_context
    member = UserFactory(email="member@example.test")
    MembershipFactory(tenant=owner_membership.tenant, user=member, role=Role.MEMBER)

    from tests.conftest import _bearer_client

    client = _bearer_client(member)
    res = client.post(
        "/api/v1/auth/me/delete/",
        {"password": "correct-horse-battery-staple"},
        format="json",
    )
    assert res.status_code == 204
    owner_membership.tenant.refresh_from_db()
    assert owner_membership.tenant.is_active is True
    member.refresh_from_db()
    assert member.is_active is False
