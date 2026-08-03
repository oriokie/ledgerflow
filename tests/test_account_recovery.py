"""Platform-side account recovery.

Support's most common request is "I can't get in". These cover the answers, and
— more importantly — the limits: staff never set a password, reactivation is not
a way around dunning, and removing a second factor is separated from ordinary
unlocking because it is the one action that lowers a security control.
"""

from __future__ import annotations

import pytest
from django.core import mail

from apps.platform_admin.models import PlatformAuditLog
from apps.platform_admin.rbac import PlatformRole
from apps.tenancy.models import Tenant
from tests.factories import MembershipFactory, UserFactory
from tests.test_platform_admin_rbac import client_for, make_staff

pytestmark = pytest.mark.django_db

REASON = "Customer called; verified identity against the last two payments."


def _totp(user):
    from django.utils import timezone

    from apps.users.mfa_models import TOTPDevice

    device = TOTPDevice(user=user, confirmed_at=timezone.now())
    device.set_secret(TOTPDevice.generate_secret())
    device.save()
    return device


# ================================================================== diagnosis
def test_lookup_names_why_the_person_cannot_get_in():
    """The whole point: an answer support can act on, not a scatter of booleans."""
    membership = MembershipFactory()
    membership.user.is_active = False
    membership.user.save(update_fields=["is_active"])

    staff = make_staff(PlatformRole.TECHNICAL_SUPPORT)
    body = client_for(staff).get(
        "/api/v1/platform/users/lookup/", {"email": membership.user.email}
    ).json()

    assert body["is_active"] is False
    assert "deactivated" in " ".join(body["blockers"]).lower()
    assert body["workspaces"][0]["tenant_id"] == str(membership.tenant_id)


def test_lookup_reports_a_suspended_workspace_as_the_blocker():
    membership = MembershipFactory()
    Tenant.objects.filter(id=membership.tenant_id).update(is_active=False)

    staff = make_staff(PlatformRole.TECHNICAL_SUPPORT)
    body = client_for(staff).get(
        "/api/v1/platform/users/lookup/", {"email": membership.user.email}
    ).json()
    assert any("suspended" in b.lower() for b in body["blockers"])


def test_lookup_is_a_404_for_an_unknown_address():
    staff = make_staff(PlatformRole.TECHNICAL_SUPPORT)
    response = client_for(staff).get(
        "/api/v1/platform/users/lookup/", {"email": "nobody@example.test"}
    )
    assert response.status_code == 404


# =============================================================== reactivation
def test_reactivating_a_locked_out_user():
    membership = MembershipFactory()
    membership.user.is_active = False
    membership.user.save(update_fields=["is_active"])
    staff = make_staff(PlatformRole.TECHNICAL_SUPPORT)

    response = client_for(staff).post(
        f"/api/v1/platform/users/{membership.user_id}/reactivate/",
        {"reason": REASON}, format="json",
    )
    assert response.status_code == 200
    assert response.data["is_active"] is True
    membership.user.refresh_from_db()
    assert membership.user.is_active


def test_reactivation_is_not_a_way_around_dunning():
    """Otherwise support becomes the workaround for non-payment."""
    membership = MembershipFactory()
    membership.user.is_active = False
    membership.user.save(update_fields=["is_active"])
    Tenant.objects.filter(id=membership.tenant_id).update(is_active=False)

    staff = make_staff(PlatformRole.TECHNICAL_SUPPORT)
    response = client_for(staff).post(
        f"/api/v1/platform/users/{membership.user_id}/reactivate/",
        {"reason": REASON}, format="json",
    )
    assert response.status_code == 422
    assert "billing" in response.data["detail"].lower()


def test_a_platform_account_cannot_be_deactivated_here():
    """Revoking platform access also ends impersonation sessions; this does not."""
    target = make_staff(PlatformRole.FINANCE)
    actor = make_staff(PlatformRole.TECHNICAL_SUPPORT)

    response = client_for(actor).post(
        f"/api/v1/platform/users/{target.user_id}/deactivate/",
        {"reason": REASON}, format="json",
    )
    assert response.status_code == 422
    assert "platform access" in response.data["detail"].lower()


# ============================================================ password resets
def test_support_can_start_a_reset_but_never_sees_the_token():
    """Staff start the flow; the customer completes it from their own mailbox.
    An operator who can set a password can log in as anyone, silently."""
    user = UserFactory()
    staff = make_staff(PlatformRole.TECHNICAL_SUPPORT)
    mail.outbox.clear()

    response = client_for(staff).post(
        f"/api/v1/platform/users/{user.id}/send-password-reset/",
        {"reason": REASON}, format="json",
    )
    assert response.status_code == 200
    # No token anywhere in the response, and none in the audit row.
    assert "token" not in str(response.data).lower()
    row = PlatformAuditLog.objects.get(action="user.password_reset_sent")
    assert "token" not in str(row.context).lower()


def test_there_is_no_endpoint_that_sets_a_password():
    """A property of the whole surface, not of one view."""
    from apps.platform_admin.api import urls as platform_urls

    paths = [str(p.pattern) for p in platform_urls.urlpatterns]
    assert not any("set-password" in p or "change-password" in p for p in paths)


# ======================================================================= MFA
def test_resetting_mfa_needs_its_own_capability():
    """Customer Success can unlock accounts but not strip a second factor —
    removing MFA on the word of a caller is the classic takeover path."""
    user = UserFactory()
    _totp(user)
    cs = make_staff(PlatformRole.CUSTOMER_SUCCESS)

    unlock = client_for(cs).post(
        f"/api/v1/platform/users/{user.id}/verify-email/", {"reason": REASON}, format="json"
    )
    assert unlock.status_code == 200, "customer success should still be able to unlock"

    response = client_for(cs).post(
        f"/api/v1/platform/users/{user.id}/reset-mfa/", {"reason": REASON}, format="json"
    )
    assert response.status_code == 403


def test_resetting_mfa_removes_every_factor_and_notifies_the_account():
    from apps.users.mfa_models import TOTPDevice

    user = UserFactory()
    _totp(user)
    staff = make_staff(PlatformRole.TECHNICAL_SUPPORT)
    mail.outbox.clear()

    response = client_for(staff).post(
        f"/api/v1/platform/users/{user.id}/reset-mfa/", {"reason": REASON}, format="json"
    )
    assert response.status_code == 200
    assert not TOTPDevice.objects.filter(user=user).exists()

    # If the request did not come from the account holder, this is how they find out.
    assert len(mail.outbox) == 1
    assert user.email in mail.outbox[0].to
    assert "did not ask" in mail.outbox[0].body


def test_resetting_mfa_on_an_account_without_it_is_refused():
    user = UserFactory()
    staff = make_staff(PlatformRole.TECHNICAL_SUPPORT)
    response = client_for(staff).post(
        f"/api/v1/platform/users/{user.id}/reset-mfa/", {"reason": REASON}, format="json"
    )
    assert response.status_code == 422


# =================================================================== auditing
def test_every_recovery_action_demands_a_specific_reason():
    user = UserFactory()
    staff = make_staff(PlatformRole.TECHNICAL_SUPPORT)
    for action in ("reactivate", "verify-email", "send-password-reset"):
        response = client_for(staff).post(
            f"/api/v1/platform/users/{user.id}/{action}/", {"reason": "help"}, format="json"
        )
        assert response.status_code in (400, 422), action


def test_recovery_actions_are_audited_against_the_customer():
    user = UserFactory()
    staff = make_staff(PlatformRole.TECHNICAL_SUPPORT)
    client_for(staff).post(
        f"/api/v1/platform/users/{user.id}/verify-email/", {"reason": REASON}, format="json"
    )
    row = PlatformAuditLog.objects.get(action="user.email_verified")
    assert row.target_id == user.id
    assert row.actor_email == staff.user.email
    assert row.reason == REASON


def test_an_auditor_cannot_recover_accounts():
    user = UserFactory()
    auditor = make_staff(PlatformRole.AUDITOR)
    response = client_for(auditor).post(
        f"/api/v1/platform/users/{user.id}/reactivate/", {"reason": REASON}, format="json"
    )
    assert response.status_code == 403


def test_an_unknown_action_is_rejected():
    user = UserFactory()
    staff = make_staff(PlatformRole.TECHNICAL_SUPPORT)
    response = client_for(staff).post(
        f"/api/v1/platform/users/{user.id}/delete-everything/", {"reason": REASON}, format="json"
    )
    assert response.status_code == 400


# ============================================================ plan catalogue
def test_the_plan_catalogue_describes_each_tier():
    staff = make_staff(PlatformRole.OWNER)
    tiers = client_for(staff).get("/api/v1/platform/plans/catalogue/").json()["tiers"]

    assert [t["tier"] for t in tiers] == ["free", "plus", "family", "business"]
    for tier in tiers:
        assert tier["pitch"], tier["tier"]
        # Every tier must add something, or it has no reason to exist.
        assert tier["adds"] or tier["tier"] == "free"


def test_nothing_that_protects_money_is_gated():
    """Reconciliation, the audit trail, export and MFA are on every tier —
    charging to verify your own books, or to leave, would be indefensible."""
    from apps.billing.plan_catalogue import UNIVERSAL, includes

    for feature in ("reconciliation", "audit_trail", "data_export", "mfa"):
        assert feature in UNIVERSAL
        assert includes("free", feature)


def test_each_tier_includes_everything_below_it():
    from apps.billing.plan_catalogue import features_for

    order = ["free", "plus", "family", "business"]
    for lower, higher in zip(order, order[1:], strict=False):
        assert features_for(lower) <= features_for(higher), f"{higher} dropped a {lower} feature"
