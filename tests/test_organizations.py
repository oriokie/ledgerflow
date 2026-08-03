"""Organizations/households (tenant types) and RBAC tests."""

from __future__ import annotations

import pytest

from apps.tenancy.models import Membership, Role, TenantType
from apps.tenancy.rbac import Capability, has_capability, outranks
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory, TenantFactory

pytestmark = pytest.mark.django_db


def test_create_workspace_with_each_type(auth_client):
    for tenant_type in [TenantType.PERSONAL, TenantType.HOUSEHOLD, TenantType.ORGANIZATION]:
        resp = auth_client.post(
            "/api/v1/tenancy/workspaces/", {"name": f"Test {tenant_type}", "type": tenant_type}, format="json"
        )
        assert resp.status_code == 201
        assert resp.data["tenant"]["type"] == tenant_type


def test_create_workspace_defaults_to_personal(auth_client):
    resp = auth_client.post("/api/v1/tenancy/workspaces/", {"name": "Default"}, format="json")
    assert resp.status_code == 201
    assert resp.data["tenant"]["type"] == TenantType.PERSONAL


# -------------------------------------------------------------- RBAC capability table
@pytest.mark.parametrize(
    "role,capability,expected",
    [
        (Role.VIEWER, Capability.LEDGER_READ, True),
        (Role.VIEWER, Capability.LEDGER_WRITE, False),
        (Role.MEMBER, Capability.LEDGER_WRITE, True),
        (Role.MEMBER, Capability.WORKSPACE_MANAGE_MEMBERS, False),
        (Role.ADMIN, Capability.WORKSPACE_MANAGE_MEMBERS, True),
        (Role.ADMIN, Capability.WORKSPACE_MANAGE_BILLING, False),
        (Role.ADMIN, Capability.WORKSPACE_DELETE, False),
        (Role.OWNER, Capability.WORKSPACE_DELETE, True),
        (Role.OWNER, Capability.WORKSPACE_MANAGE_BILLING, True),
    ],
)
def test_role_capability_table(role, capability, expected):
    membership = MembershipFactory.build(role=role)  # unsaved is fine — pure function
    assert has_capability(membership, capability) is expected


def test_has_capability_with_no_membership_is_always_false():
    assert has_capability(None, Capability.LEDGER_READ) is False


def test_outranks():
    owner = MembershipFactory.build(role=Role.OWNER)
    admin = MembershipFactory.build(role=Role.ADMIN)
    member = MembershipFactory.build(role=Role.MEMBER)
    assert outranks(owner, admin) is True
    assert outranks(admin, owner) is False
    assert outranks(admin, member) is True


# -------------------------------------------------------------- member management API
def test_list_members(tenant_context):
    membership, client = tenant_context
    other = MembershipFactory(tenant=membership.tenant, role=Role.MEMBER)
    resp = client.get("/api/v1/tenancy/workspaces/members/", HTTP_X_TENANT_ID=str(membership.tenant_id))
    assert resp.status_code == 200
    emails = {m["email"] for m in resp.data}
    assert {membership.user.email, other.user.email} == emails


def test_owner_can_change_member_role(tenant_context):
    owner_membership, client = tenant_context
    target = MembershipFactory(tenant=owner_membership.tenant, role=Role.MEMBER)
    resp = client.patch(
        f"/api/v1/tenancy/workspaces/members/{target.id}/",
        {"role": "admin"},
        format="json",
        HTTP_X_TENANT_ID=str(owner_membership.tenant_id),
    )
    assert resp.status_code == 200
    target.refresh_from_db()
    assert target.role == Role.ADMIN


def test_member_cannot_change_roles(tenant_context):
    owner_membership, owner_client = tenant_context
    member = MembershipFactory(tenant=owner_membership.tenant, role=Role.MEMBER)
    member_client = _bearer_client(member.user, tenant_id=member.tenant_id)

    other = MembershipFactory(tenant=owner_membership.tenant, role=Role.VIEWER)
    resp = member_client.patch(
        f"/api/v1/tenancy/workspaces/members/{other.id}/",
        {"role": "admin"},
        format="json",
        HTTP_X_TENANT_ID=str(owner_membership.tenant_id),
    )
    assert resp.status_code == 403


def test_admin_cannot_promote_self_above_own_role(tenant_context):
    owner_membership, owner_client = tenant_context
    admin = MembershipFactory(tenant=owner_membership.tenant, role=Role.ADMIN)
    admin_client = _bearer_client(admin.user, tenant_id=admin.tenant_id)

    resp = admin_client.patch(
        f"/api/v1/tenancy/workspaces/members/{admin.id}/",
        {"role": "owner"},
        format="json",
        HTTP_X_TENANT_ID=str(admin.tenant_id),
    )
    assert resp.status_code == 403


def test_cannot_demote_the_last_owner(tenant_context):
    owner_membership, client = tenant_context
    resp = client.patch(
        f"/api/v1/tenancy/workspaces/members/{owner_membership.id}/",
        {"role": "admin"},
        format="json",
        HTTP_X_TENANT_ID=str(owner_membership.tenant_id),
    )
    assert resp.status_code == 409
    owner_membership.refresh_from_db()
    assert owner_membership.role == Role.OWNER


def test_can_demote_owner_if_another_owner_exists(tenant_context):
    owner_membership, client = tenant_context
    co_owner = MembershipFactory(tenant=owner_membership.tenant, role=Role.OWNER)
    resp = client.patch(
        f"/api/v1/tenancy/workspaces/members/{co_owner.id}/",
        {"role": "admin"},
        format="json",
        HTTP_X_TENANT_ID=str(owner_membership.tenant_id),
    )
    assert resp.status_code == 200


def test_remove_member(tenant_context):
    owner_membership, client = tenant_context
    target = MembershipFactory(tenant=owner_membership.tenant, role=Role.MEMBER)
    resp = client.delete(
        f"/api/v1/tenancy/workspaces/members/{target.id}/", HTTP_X_TENANT_ID=str(owner_membership.tenant_id)
    )
    assert resp.status_code == 204
    assert not Membership.objects.filter(id=target.id).exists()


def test_cannot_remove_last_owner(tenant_context):
    owner_membership, client = tenant_context
    resp = client.delete(
        f"/api/v1/tenancy/workspaces/members/{owner_membership.id}/",
        HTTP_X_TENANT_ID=str(owner_membership.tenant_id),
    )
    assert resp.status_code == 409


def test_member_can_remove_self():
    """A member can always leave a workspace, even without manage-members
    capability — that's the self-exception in `remove_member`."""
    tenant = TenantFactory()
    owner = MembershipFactory(tenant=tenant, role=Role.OWNER)
    leaving_member = MembershipFactory(tenant=tenant, role=Role.MEMBER)
    del owner

    from apps.tenancy.services import remove_member

    remove_member(actor_membership=leaving_member, target_membership=leaving_member)
    assert not Membership.objects.filter(id=leaving_member.id).exists()


def test_cross_tenant_member_actions_rejected(tenant_context):
    owner_membership, client = tenant_context
    other_tenant_member = MembershipFactory()  # a completely different workspace
    resp = client.delete(
        f"/api/v1/tenancy/workspaces/members/{other_tenant_member.id}/",
        HTTP_X_TENANT_ID=str(owner_membership.tenant_id),
    )
    assert resp.status_code == 404  # not found *within this workspace*, not leaked
