"""Invitation lifecycle tests."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.tenancy.models import Invitation, InvitationStatus, Membership, Role
from apps.tenancy.services import InsufficientRoleError, create_invitation
from tests.conftest import _bearer_client
from tests.factories import InvitationFactory, MembershipFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_admin_can_create_invitation(tenant_context):
    owner_membership, client = tenant_context
    resp = client.post(
        "/api/v1/tenancy/workspaces/invitations/",
        {"email": "newperson@example.com", "role": "member"},
        format="json",
        HTTP_X_TENANT_ID=str(owner_membership.tenant_id),
    )
    assert resp.status_code == 201
    assert resp.data["email"] == "newperson@example.com"
    assert resp.data["status"] == "pending"
    # the raw token is never returned via the API — only sent by email
    assert "token" not in resp.data


def test_invitation_email_is_sent(tenant_context, django_capture_on_commit_callbacks):
    """Delivery is deferred to `transaction.on_commit`.

    It used to be dispatched inline, which raced the commit: the worker could
    look the invitation up before it existed, find nothing, and return silently
    — so the inviter saw success and nobody was emailed. This test now has to
    let the commit hooks run, which is exactly the property being asserted.
    """
    owner_membership, client = tenant_context
    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            "/api/v1/tenancy/workspaces/invitations/",
            {"email": "newperson@example.com", "role": "member"},
            format="json",
            HTTP_X_TENANT_ID=str(owner_membership.tenant_id),
        )
    assert len(mail.outbox) == 1
    assert "newperson@example.com" in mail.outbox[0].to
    # And the link must point at the SPA route, not a string-sliced OAuth URL.
    assert "/invite?token=" in mail.outbox[0].body


def test_member_cannot_create_invitation(tenant_context):
    owner_membership, _owner_client = tenant_context
    member = MembershipFactory(tenant=owner_membership.tenant, role=Role.MEMBER)
    member_client = _bearer_client(member.user, tenant_id=member.tenant_id)
    resp = member_client.post(
        "/api/v1/tenancy/workspaces/invitations/",
        {"email": "x@example.com", "role": "member"},
        format="json",
        HTTP_X_TENANT_ID=str(owner_membership.tenant_id),
    )
    assert resp.status_code == 403


def test_admin_cannot_invite_someone_as_owner(tenant_context):
    owner_membership, _owner_client = tenant_context
    admin = MembershipFactory(tenant=owner_membership.tenant, role=Role.ADMIN)
    admin_client = _bearer_client(admin.user, tenant_id=admin.tenant_id)
    resp = admin_client.post(
        "/api/v1/tenancy/workspaces/invitations/",
        {"email": "x@example.com", "role": "owner"},
        format="json",
        HTTP_X_TENANT_ID=str(admin.tenant_id),
    )
    assert resp.status_code == 403


def test_accept_invitation_creates_membership(tenant_context):
    owner_membership, client = tenant_context
    invitee = UserFactory(email="invitee@example.com")
    invitation, raw_token = create_invitation(
        tenant=owner_membership.tenant,
        invited_by_membership=owner_membership,
        email=invitee.email,
        role=Role.MEMBER,
    )

    invitee_client = _bearer_client(invitee)
    resp = invitee_client.post("/api/v1/tenancy/invitations/accept/", {"token": raw_token}, format="json")
    assert resp.status_code == 201
    assert Membership.objects.filter(tenant=owner_membership.tenant, user=invitee, role=Role.MEMBER).exists()

    invitation.refresh_from_db()
    assert invitation.status == InvitationStatus.ACCEPTED
    assert invitation.accepted_by == invitee


def test_accept_invitation_wrong_email_rejected(tenant_context):
    owner_membership, _client = tenant_context
    invitee = UserFactory(email="invitee@example.com")
    _invitation, raw_token = create_invitation(
        tenant=owner_membership.tenant,
        invited_by_membership=owner_membership,
        email="someone-else@example.com",
        role=Role.MEMBER,
    )

    invitee_client = _bearer_client(invitee)
    resp = invitee_client.post("/api/v1/tenancy/invitations/accept/", {"token": raw_token}, format="json")
    assert resp.status_code == 400


def test_accept_invitation_bad_token_rejected(auth_client):
    resp = auth_client.post(
        "/api/v1/tenancy/invitations/accept/", {"token": "not-a-real-token"}, format="json"
    )
    assert resp.status_code == 400


def test_accept_expired_invitation_rejected(tenant_context):
    owner_membership, _client = tenant_context
    invitee = UserFactory(email="invitee@example.com")
    _invitation, raw_token = create_invitation(
        tenant=owner_membership.tenant,
        invited_by_membership=owner_membership,
        email=invitee.email,
        role=Role.MEMBER,
    )
    # simulate time passing
    Invitation.objects.filter(email=invitee.email).update(expires_at=timezone.now() - timedelta(days=1))

    invitee_client = _bearer_client(invitee)
    resp = invitee_client.post("/api/v1/tenancy/invitations/accept/", {"token": raw_token}, format="json")
    assert resp.status_code == 400


def test_accept_already_accepted_invitation_rejected(tenant_context):
    owner_membership, _client = tenant_context
    invitee = UserFactory(email="invitee@example.com")
    _invitation, raw_token = create_invitation(
        tenant=owner_membership.tenant,
        invited_by_membership=owner_membership,
        email=invitee.email,
        role=Role.MEMBER,
    )
    invitee_client = _bearer_client(invitee)
    first = invitee_client.post("/api/v1/tenancy/invitations/accept/", {"token": raw_token}, format="json")
    assert first.status_code == 201

    second = invitee_client.post("/api/v1/tenancy/invitations/accept/", {"token": raw_token}, format="json")
    assert second.status_code == 400


def test_accept_invitation_when_already_a_member_rejected(tenant_context):
    owner_membership, _client = tenant_context
    already_member = MembershipFactory(tenant=owner_membership.tenant, role=Role.VIEWER)
    _invitation, raw_token = create_invitation(
        tenant=owner_membership.tenant,
        invited_by_membership=owner_membership,
        email=already_member.user.email,
        role=Role.MEMBER,
    )
    client = _bearer_client(already_member.user)
    resp = client.post("/api/v1/tenancy/invitations/accept/", {"token": raw_token}, format="json")
    assert resp.status_code == 400


def test_revoke_invitation(tenant_context):
    owner_membership, client = tenant_context
    invitation = InvitationFactory(tenant=owner_membership.tenant)
    resp = client.delete(
        f"/api/v1/tenancy/workspaces/invitations/{invitation.id}/",
        HTTP_X_TENANT_ID=str(owner_membership.tenant_id),
    )
    assert resp.status_code == 204
    invitation.refresh_from_db()
    assert invitation.status == InvitationStatus.REVOKED


def test_revoked_invitation_cannot_be_accepted(tenant_context):
    owner_membership, client = tenant_context
    invitee = UserFactory(email="invitee@example.com")
    invitation, raw_token = create_invitation(
        tenant=owner_membership.tenant,
        invited_by_membership=owner_membership,
        email=invitee.email,
        role=Role.MEMBER,
    )
    client.delete(
        f"/api/v1/tenancy/workspaces/invitations/{invitation.id}/",
        HTTP_X_TENANT_ID=str(owner_membership.tenant_id),
    )

    invitee_client = _bearer_client(invitee)
    resp = invitee_client.post("/api/v1/tenancy/invitations/accept/", {"token": raw_token}, format="json")
    assert resp.status_code == 400


def test_list_pending_invitations(tenant_context):
    owner_membership, client = tenant_context
    InvitationFactory(tenant=owner_membership.tenant, email="a@example.com")
    InvitationFactory(tenant=owner_membership.tenant, email="b@example.com")
    InvitationFactory(tenant=owner_membership.tenant, email="c@example.com", status=InvitationStatus.REVOKED)

    resp = client.get(
        "/api/v1/tenancy/workspaces/invitations/", HTTP_X_TENANT_ID=str(owner_membership.tenant_id)
    )
    assert resp.status_code == 200
    emails = {inv["email"] for inv in resp.data}
    assert emails == {"a@example.com", "b@example.com"}  # revoked one excluded


def test_service_layer_rejects_invite_above_own_role_directly():
    owner_membership = MembershipFactory(role=Role.ADMIN)
    with pytest.raises(InsufficientRoleError):
        create_invitation(
            tenant=owner_membership.tenant,
            invited_by_membership=owner_membership,
            email="x@example.com",
            role=Role.OWNER,
        )


def test_preview_invitation_returns_workspace_role_and_inviter(tenant_context, api_client):
    owner_membership, _client = tenant_context
    invitation, raw_token = create_invitation(
        tenant=owner_membership.tenant,
        invited_by_membership=owner_membership,
        email="invitee@example.com",
        role=Role.MEMBER,
    )

    # No auth header at all -- the whole point is this works before sign-in.
    resp = api_client.get(f"/api/v1/tenancy/invitations/{raw_token}/")
    assert resp.status_code == 200
    assert resp.data["workspace_name"] == owner_membership.tenant.name
    assert resp.data["role"] == "member"
    assert resp.data["invited_by_display"] == owner_membership.user.full_name
    # Nothing about the workspace's data leaks out.
    assert set(resp.data.keys()) == {"workspace_name", "role", "invited_by_display"}


def test_preview_invitation_bad_token_rejected(api_client):
    resp = api_client.get("/api/v1/tenancy/invitations/not-a-real-token/")
    assert resp.status_code == 400


def test_preview_expired_invitation_rejected(tenant_context, api_client):
    owner_membership, _client = tenant_context
    invitation, raw_token = create_invitation(
        tenant=owner_membership.tenant,
        invited_by_membership=owner_membership,
        email="invitee@example.com",
        role=Role.MEMBER,
    )
    invitation.expires_at = timezone.now() - timedelta(days=1)
    invitation.save(update_fields=["expires_at"])

    resp = api_client.get(f"/api/v1/tenancy/invitations/{raw_token}/")
    assert resp.status_code == 400


def test_preview_does_not_accept_the_invitation(tenant_context, api_client):
    """Peeking is read-only -- it must not consume the invitation."""
    owner_membership, _client = tenant_context
    invitee = UserFactory(email="invitee@example.com")
    invitation, raw_token = create_invitation(
        tenant=owner_membership.tenant,
        invited_by_membership=owner_membership,
        email=invitee.email,
        role=Role.MEMBER,
    )

    api_client.get(f"/api/v1/tenancy/invitations/{raw_token}/")

    invitation.refresh_from_db()
    assert invitation.status == InvitationStatus.PENDING

    invitee_client = _bearer_client(invitee)
    resp = invitee_client.post("/api/v1/tenancy/invitations/accept/", {"token": raw_token}, format="json")
    assert resp.status_code == 201


def test_invitation_token_is_hashed_at_rest(tenant_context):
    owner_membership, _client = tenant_context
    invitation, raw_token = create_invitation(
        tenant=owner_membership.tenant,
        invited_by_membership=owner_membership,
        email="x@example.com",
        role=Role.MEMBER,
    )
    assert invitation.token_hash != raw_token
    assert raw_token not in invitation.token_hash
