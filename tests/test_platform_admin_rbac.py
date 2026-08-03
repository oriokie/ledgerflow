"""Platform workspace: access control, audit trail and staff governance.

The security properties are the point of this module, so they are tested as
properties ("a non-staff user cannot reach any platform endpoint") rather than
endpoint by endpoint.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.platform_admin.models import PlatformAuditLog, PlatformStaff
from apps.platform_admin.permissions import ip_allowed
from apps.platform_admin.rbac import (
    ALL_CAPABILITIES,
    ROLE_CAPABILITIES,
    PlatformCapability as Cap,
    PlatformRole,
    UnknownCapabilityError,
    capabilities_for,
)
from apps.platform_admin.services import staff as staff_service
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _enable_mfa(user):
    """Platform access requires an enrolled second factor by default.

    `confirmed_at` is what makes a device count — an in-progress enrolment
    cannot satisfy a challenge, so it must not satisfy this check either.
    """
    from django.utils import timezone

    from apps.users.mfa_models import TOTPDevice

    device = TOTPDevice(user=user, confirmed_at=timezone.now())
    device.set_secret(TOTPDevice.generate_secret())
    device.save()
    return user


def make_staff(role=PlatformRole.OWNER, *, mfa=True, **kwargs) -> PlatformStaff:
    user = UserFactory()
    if mfa:
        _enable_mfa(user)
    return PlatformStaff.objects.create(user=user, role=role, **kwargs)


def client_for(staff: PlatformStaff) -> APIClient:
    client = APIClient()
    token = RefreshToken.for_user(staff.user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


# ======================================================================== rbac
def test_owner_holds_every_capability():
    assert ROLE_CAPABILITIES[PlatformRole.OWNER] == ALL_CAPABILITIES


def test_auditor_can_read_but_never_write():
    caps = ROLE_CAPABILITIES[PlatformRole.AUDITOR]
    assert Cap.TENANT_READ in caps
    for write_cap in (
        Cap.TENANT_WRITE,
        Cap.TENANT_SUSPEND,
        Cap.SUBSCRIPTION_WRITE,
        Cap.REFUND_APPROVE,
        Cap.STAFF_MANAGE,
        Cap.COUPON_WRITE,
    ):
        assert write_cap not in caps


def test_customer_success_can_request_a_refund_but_not_approve_it():
    """Separation of duties: promising a refund and paying it are different jobs."""
    caps = ROLE_CAPABILITIES[PlatformRole.CUSTOMER_SUCCESS]
    assert Cap.REFUND_REQUEST in caps
    assert Cap.REFUND_APPROVE not in caps


def test_finance_approves_refunds_but_cannot_touch_product_state():
    caps = ROLE_CAPABILITIES[PlatformRole.FINANCE]
    assert Cap.REFUND_APPROVE in caps
    assert Cap.TENANT_SUSPEND not in caps
    assert Cap.SUBSCRIPTION_WRITE not in caps


def test_only_the_owner_may_appoint_staff():
    for role in PlatformRole:
        holds = Cap.STAFF_MANAGE in ROLE_CAPABILITIES[role]
        assert holds == (role == PlatformRole.OWNER), role


def test_denials_beat_grants():
    """A revocation must not be defeated by also appearing in a grant list."""
    caps = capabilities_for(
        PlatformRole.AUDITOR,
        extra=[Cap.TENANT_SUSPEND.value],
        denied=[Cap.TENANT_SUSPEND.value],
    )
    assert Cap.TENANT_SUSPEND not in caps


def test_extra_capabilities_widen_a_role():
    caps = capabilities_for(PlatformRole.AUDITOR, extra=[Cap.TENANT_SUSPEND.value])
    assert Cap.TENANT_SUSPEND in caps


def test_an_unknown_capability_fails_loudly():
    """A typo in a grant must not look like it succeeded while conferring nothing."""
    with pytest.raises(UnknownCapabilityError):
        capabilities_for(PlatformRole.AUDITOR, extra=["tenant.suspended"])


def test_an_unknown_role_fails_loudly():
    with pytest.raises(UnknownCapabilityError):
        capabilities_for("supreme_leader")


# ================================================================= permissions
def test_a_plain_user_cannot_reach_the_platform_api():
    user = UserFactory()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    assert client.get("/api/v1/platform/dashboard/").status_code == 403


def test_an_anonymous_request_is_rejected():
    assert APIClient().get("/api/v1/platform/dashboard/").status_code == 401


def test_a_tenant_owner_has_no_platform_authority():
    """Workspace authority and platform authority are different systems."""
    from tests.factories import MembershipFactory

    membership = MembershipFactory()
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(membership.user).access_token}"
    )
    assert client.get("/api/v1/platform/tenants/").status_code == 403


def test_capability_is_enforced_per_endpoint():
    auditor = make_staff(PlatformRole.AUDITOR)
    client = client_for(auditor)

    assert client.get("/api/v1/platform/tenants/").status_code == 200
    assert client.post("/api/v1/platform/staff/", {}, format="json").status_code == 403


def test_a_revoked_staff_member_loses_access_immediately():
    member = make_staff(PlatformRole.ADMIN)
    client = client_for(member)
    assert client.get("/api/v1/platform/dashboard/").status_code == 200

    member.is_active = False
    member.save(update_fields=["is_active"])
    assert client.get("/api/v1/platform/dashboard/").status_code == 403


def test_mfa_is_required_by_default():
    """Platform staff handle other people's money; a second factor is policy."""
    member = make_staff(PlatformRole.ADMIN, mfa=False)
    response = client_for(member).get("/api/v1/platform/dashboard/")
    assert response.status_code == 403


def test_mfa_can_be_waived_explicitly():
    member = make_staff(PlatformRole.ADMIN, mfa=False, require_mfa=False)
    assert client_for(member).get("/api/v1/platform/dashboard/").status_code == 200


def test_the_platform_api_ignores_a_tenant_header():
    """A misrouted tenant request must not inherit tenant scoping here."""
    from tests.factories import MembershipFactory

    membership = MembershipFactory()
    member = make_staff(PlatformRole.OWNER)
    client = client_for(member)
    response = client.get(
        "/api/v1/platform/dashboard/", HTTP_X_TENANT_ID=str(membership.tenant_id)
    )
    assert response.status_code == 200


# ---------------------------------------------------------------- ip allowlist
def test_an_empty_allowlist_permits_everything():
    assert ip_allowed("203.0.113.9", [])


def test_a_non_empty_allowlist_is_fail_closed():
    assert not ip_allowed("203.0.113.9", ["198.51.100.0/24"])
    assert ip_allowed("198.51.100.7", ["198.51.100.0/24"])


def test_a_malformed_allowlist_entry_does_not_widen_access():
    """A typo in one office range must not let everyone in."""
    assert not ip_allowed("203.0.113.9", ["not-an-ip"])
    assert ip_allowed("198.51.100.7", ["not-an-ip", "198.51.100.0/24"])


def test_a_missing_client_ip_is_refused_when_restricted():
    assert not ip_allowed(None, ["198.51.100.0/24"])


def test_ip_restriction_is_enforced_on_a_real_request():
    member = make_staff(PlatformRole.OWNER, allowed_ips=["198.51.100.0/24"])
    response = client_for(member).get("/api/v1/platform/dashboard/", REMOTE_ADDR="203.0.113.5")
    assert response.status_code == 403


# ======================================================================= audit
def test_the_audit_log_is_append_only_at_the_database_level():
    """Application convention is not a control; a trigger is."""
    row = PlatformAuditLog.objects.create(action="test.action", module="tests")

    with pytest.raises(Exception):
        with transaction.atomic():
            PlatformAuditLog.objects.filter(pk=row.pk).update(action="tampered")

    with pytest.raises(Exception):
        with transaction.atomic():
            PlatformAuditLog.objects.filter(pk=row.pk).delete()

    row.refresh_from_db()
    assert row.action == "test.action"


def test_audit_rows_keep_the_actor_email_after_the_user_is_deleted():
    """An audit trail that goes anonymous has failed at its only job."""
    member = make_staff(PlatformRole.OWNER)
    email = member.user.email
    from apps.platform_admin.audit import record

    record(action="tenant.suspended", staff=member, module="tenants", reason="testing")
    member.user.delete()

    row = PlatformAuditLog.objects.get(action="tenant.suspended")
    assert row.actor_email == email


def test_audit_records_capture_request_context():
    member = make_staff(PlatformRole.OWNER)
    from tests.factories import MembershipFactory

    membership = MembershipFactory()
    client_for(member).post(
        f"/api/v1/platform/tenants/{membership.tenant_id}/suspend/",
        {"reason": "Confirmed fraudulent chargebacks"},
        format="json",
        REMOTE_ADDR="198.51.100.20",
        HTTP_USER_AGENT="AdminConsole/1.0",
    )
    row = PlatformAuditLog.objects.get(action="tenant.suspended")
    assert row.ip_address == "198.51.100.20"
    assert row.user_agent == "AdminConsole/1.0"
    assert row.reason == "Confirmed fraudulent chargebacks"
    assert row.changes == {"is_active": [True, False]}


# ======================================================================= staff
def test_a_staff_member_cannot_grant_authority_they_lack():
    """Otherwise anyone with staff.manage is effectively an owner."""
    admin = make_staff(PlatformRole.ADMIN)
    target = UserFactory()
    with pytest.raises(staff_service.StaffError):
        staff_service.appoint(user=target, role=PlatformRole.OWNER, actor=admin)


def test_a_staff_member_cannot_promote_themselves():
    admin = make_staff(PlatformRole.ADMIN)
    with pytest.raises(staff_service.StaffError):
        staff_service.update(staff=admin, actor=admin, role=PlatformRole.OWNER)


def test_a_staff_member_cannot_revoke_their_own_access():
    owner = make_staff(PlatformRole.OWNER)
    with pytest.raises(staff_service.StaffError):
        staff_service.revoke(staff=owner, actor=owner, reason="oops")


def test_the_last_owner_cannot_be_revoked():
    """A platform with no owner has nobody who can appoint one."""
    first = make_staff(PlatformRole.OWNER)
    second = make_staff(PlatformRole.OWNER)
    staff_service.revoke(staff=second, actor=first, reason="Left the company")

    third = make_staff(PlatformRole.ADMIN)
    with pytest.raises(staff_service.StaffError):
        staff_service.revoke(staff=first, actor=third, reason="Trying anyway")


def test_appointing_the_same_user_twice_is_refused():
    owner = make_staff(PlatformRole.OWNER)
    target = UserFactory()
    staff_service.appoint(user=target, role=PlatformRole.AUDITOR, actor=owner)
    with pytest.raises(staff_service.StaffError):
        staff_service.appoint(user=target, role=PlatformRole.FINANCE, actor=owner)


def test_a_user_can_only_hold_one_platform_role():
    owner = make_staff(PlatformRole.OWNER)
    target = UserFactory()
    staff_service.appoint(user=target, role=PlatformRole.AUDITOR, actor=owner)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PlatformStaff.objects.create(user=target, role=PlatformRole.FINANCE)


def test_appointment_is_audited_with_the_granting_actor():
    owner = make_staff(PlatformRole.OWNER)
    target = UserFactory()
    staff_service.appoint(user=target, role=PlatformRole.FINANCE, actor=owner)

    row = PlatformAuditLog.objects.get(action="staff.appointed")
    assert row.actor_email == owner.user.email
    assert row.changes["role"] == [None, PlatformRole.FINANCE.value]


def test_bootstrap_appointment_skips_the_escalation_guard():
    """The first owner has nobody to authorise them — that is the whole point."""
    user = UserFactory()
    member = staff_service.appoint(user=user, role=PlatformRole.OWNER, actor=None)
    assert member.role == PlatformRole.OWNER


def test_me_returns_resolved_capabilities_not_just_a_role():
    member = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    body = client_for(member).get("/api/v1/platform/me/").json()

    assert body["role"] == PlatformRole.CUSTOMER_SUCCESS.value
    assert Cap.REFUND_REQUEST.value in body["capabilities"]
    assert Cap.REFUND_APPROVE.value not in body["capabilities"]
