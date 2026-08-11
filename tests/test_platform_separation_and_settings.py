"""Operator/customer separation, and runtime platform configuration."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.platform_admin import settings_store
from apps.platform_admin.models import PlatformStaff
from apps.platform_admin.rbac import PlatformRole
from apps.platform_admin.separation import PlatformSeparationError, is_platform_staff
from apps.platform_admin.services import staff as staff_service
from apps.tenancy import services as tenancy
from apps.tenancy.models import Membership
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory, UserFactory
from tests.test_platform_admin_rbac import client_for, make_staff

pytestmark = pytest.mark.django_db


# ================================================================ separation
def test_platform_staff_cannot_create_a_workspace():
    """An operator account acts on other people's workspaces, not its own."""
    member = make_staff(PlatformRole.OWNER)
    with pytest.raises(PlatformSeparationError):
        tenancy.create_workspace(name="My Household", owner=member.user)


def test_platform_staff_cannot_accept_an_invitation():
    """The other way an account becomes a tenant member."""
    member = make_staff(PlatformRole.CUSTOMER_SUCCESS)
    host = MembershipFactory()
    _, raw_token = tenancy.create_invitation(
        tenant=host.tenant,
        invited_by_membership=host,
        email=member.user.email,
        role="member",
    )
    with pytest.raises(PlatformSeparationError):
        tenancy.accept_invitation(raw_token=raw_token, user=member.user)


def test_the_api_returns_403_not_500():
    member = make_staff(PlatformRole.OWNER)
    client = _bearer_client(member.user)
    response = client.post(
        "/api/v1/tenancy/workspaces/", {"name": "Mine", "base_currency": "USD"}, format="json"
    )
    assert response.status_code == 403
    assert "administration account" in str(response.data)


def test_an_ordinary_user_is_unaffected():
    user = UserFactory()
    workspace = tenancy.create_workspace(name="Household", owner=user)
    assert Membership.objects.filter(tenant=workspace, user=user).exists()


def test_separation_can_be_disabled_for_a_solo_operator(settings):
    """A founder dogfooding their own product is a real situation."""
    settings.PLATFORM_STAFF_SEPARATE_FROM_TENANTS = False
    member = make_staff(PlatformRole.OWNER)

    workspace = tenancy.create_workspace(name="Founder Household", owner=member.user)
    assert Membership.objects.filter(tenant=workspace, user=member.user).exists()


def test_revoking_platform_access_restores_ordinary_customer_use():
    """Losing an admin role should not lock someone out of both halves."""
    owner = make_staff(PlatformRole.OWNER)
    member = make_staff(PlatformRole.AUDITOR)
    staff_service.revoke(staff=member, actor=owner, reason="Left the platform team")

    assert not is_platform_staff(member.user)
    assert tenancy.create_workspace(name="Now a customer", owner=member.user)


def test_appointment_records_pre_existing_memberships_rather_than_severing_them():
    """Their household is not ours to delete because they joined support."""
    from apps.platform_admin.models import PlatformAuditLog

    existing = MembershipFactory()
    owner = make_staff(PlatformRole.OWNER)

    staff_service.appoint(user=existing.user, role=PlatformRole.TECHNICAL_SUPPORT, actor=owner)

    assert Membership.objects.filter(user=existing.user).exists()
    row = PlatformAuditLog.objects.filter(action="staff.appointed").latest("created_at")
    assert row.context["pre_existing_workspace_memberships"] == 1


def test_the_user_payload_flags_a_platform_account():
    """The customer app needs this to route an operator to the console."""
    member = make_staff(PlatformRole.OWNER)
    body = _bearer_client(member.user).get("/api/v1/auth/me/").json()
    assert body["is_platform_staff"] is True


def test_the_user_payload_flags_an_ordinary_account():
    membership = MembershipFactory()
    body = _bearer_client(membership.user).get("/api/v1/auth/me/").json()
    assert body["is_platform_staff"] is False


def test_the_seeded_admin_owns_no_workspace(settings):
    settings.DEBUG = True
    call_command("seed_platform_demo", verbosity=0, admin_only=True)

    staff = PlatformStaff.objects.get(role=PlatformRole.OWNER)
    assert not Membership.objects.filter(user=staff.user).exists()


# ================================================================== settings
def test_a_setting_falls_back_to_the_environment(settings):
    settings.LLM_MODEL = "gemini-2.0-flash"
    assert settings_store.get("ai.model") == "gemini-2.0-flash"


def test_a_database_override_beats_the_environment(settings):
    settings.LLM_MODEL = "from-env"
    settings_store.set_value(key="ai.model", raw="from-console")
    assert settings_store.get("ai.model") == "from-console"


def test_clearing_an_override_falls_back_rather_than_blanking(settings):
    """Clearing a field in the console must restore the environment value, not
    set the setting to empty."""
    settings.LLM_MODEL = "from-env"
    settings_store.set_value(key="ai.model", raw="from-console")
    settings_store.clear(key="ai.model")
    assert settings_store.get("ai.model") == "from-env"


def test_the_built_in_default_applies_when_nothing_is_configured():
    assert settings_store.get("invoice.payment_terms_days") == 14


def test_values_are_coerced_by_their_declared_kind():
    settings_store.set_value(key="invoice.default_tax_rate_bps", raw="2000")
    settings_store.set_value(key="ai.enabled", raw=True)

    assert settings_store.get("invoice.default_tax_rate_bps") == 2000
    assert settings_store.get("ai.enabled") is True


def test_an_unknown_key_is_rejected():
    with pytest.raises(KeyError):
        settings_store.set_value(key="ai.secret_backdoor", raw="x")
    with pytest.raises(KeyError):
        settings_store.get("nope")


def test_a_secret_is_encrypted_at_rest():
    from apps.platform_admin.settings_store import PlatformSetting

    settings_store.set_value(key="payments.stripe_secret_key", raw="sk_live_supersecret")
    row = PlatformSetting.objects.get(key="payments.stripe_secret_key")

    assert row.value == ""
    assert "sk_live_supersecret" not in row.encrypted_value
    assert row.get_value() == "sk_live_supersecret"


def test_a_secret_is_never_returned_by_the_api():
    """A compromised admin session must not become a credential dump."""
    settings_store.set_value(key="payments.stripe_secret_key", raw="sk_live_supersecret")
    member = make_staff(PlatformRole.OWNER)

    body = client_for(member).get("/api/v1/platform/settings/").json()
    stripe = next(s for s in body["settings"] if s["key"] == "payments.stripe_secret_key")

    assert stripe["value"] is None
    assert stripe["is_set"] is True
    assert stripe["source"] == "database"
    assert "sk_live_supersecret" not in str(body)


def test_a_non_secret_setting_is_readable():
    member = make_staff(PlatformRole.OWNER)
    body = client_for(member).get("/api/v1/platform/settings/").json()
    terms = next(s for s in body["settings"] if s["key"] == "invoice.payment_terms_days")
    assert terms["value"] == 14


def test_the_api_reports_where_each_value_came_from(settings):
    settings.LLM_MODEL = "from-env"
    member = make_staff(PlatformRole.OWNER)

    body = client_for(member).get("/api/v1/platform/settings/").json()
    by_key = {s["key"]: s for s in body["settings"]}

    assert by_key["ai.model"]["source"] == "environment"
    assert by_key["invoice.payment_terms_days"]["source"] == "default"


def test_writing_a_setting_is_audited_without_recording_the_secret():
    from apps.platform_admin.models import PlatformAuditLog

    member = make_staff(PlatformRole.OWNER)
    response = client_for(member).post(
        "/api/v1/platform/settings/",
        {"key": "payments.stripe_secret_key", "value": "sk_live_rotated", "reason": "Quarterly rotation"},
        format="json",
    )
    assert response.status_code == 200

    row = PlatformAuditLog.objects.get(action="setting.updated")
    assert row.reason == "Quarterly rotation"
    # An audit log holding live credentials is a liability, not a control.
    assert "sk_live_rotated" not in str(row.changes)
    assert row.changes["payments.stripe_secret_key"] == [None, "<set>"]


def test_editing_settings_needs_staff_manage_not_merely_read():
    auditor = make_staff(PlatformRole.AUDITOR)
    client = client_for(auditor)

    assert client.get("/api/v1/platform/settings/").status_code == 200
    assert (
        client.post(
            "/api/v1/platform/settings/", {"key": "ai.enabled", "value": True}, format="json"
        ).status_code
        == 403
    )


def test_an_unknown_key_is_a_field_error_not_a_500():
    member = make_staff(PlatformRole.OWNER)
    response = client_for(member).post(
        "/api/v1/platform/settings/", {"key": "made.up", "value": 1}, format="json"
    )
    assert response.status_code == 400
    assert "key" in response.json()


def test_ai_availability_is_a_platform_decision(settings):
    """Gate one of three: the operator decides whether AI exists at all."""
    settings.LLM_ENABLED = False
    assert settings_store.ai_available() is False

    settings_store.set_value(key="ai.enabled", raw=True)
    assert settings_store.ai_available() is True


def test_the_invoice_issuer_is_editable_without_a_deploy():
    from apps.billing.invoice_pdf import issuer_details

    settings_store.set_value(key="invoice.issuer_name", raw="Acme Kenya Ltd")
    settings_store.set_value(key="invoice.issuer_tax_id", raw="P051234567X")

    details = issuer_details()
    assert details["name"] == "Acme Kenya Ltd"
    assert details["tax_id"] == "P051234567X"


def test_a_payment_provider_can_be_switched_off():
    assert settings_store.payment_provider_enabled("stripe") is True
    settings_store.set_value(key="payments.stripe_enabled", raw=False)
    assert settings_store.payment_provider_enabled("stripe") is False


# =================================================== closed-set settings
def test_a_closed_set_setting_refuses_a_value_outside_it():
    """The illustration style drives what every surface in the product draws,
    including signed-out ones. A typo'd value would store happily and the only
    symptom would be blank artwork everywhere — a failure with no error
    attached to it, on pages nobody is watching."""
    with pytest.raises(settings_store.InvalidSettingValue):
        settings_store.set_value(key="appearance.illustration_style", raw="doodles")

    settings_store.set_value(key="appearance.illustration_style", raw="doodle")
    assert settings_store.get("appearance.illustration_style") == "doodle"

    # The animated set. Kept in this test rather than its own so a fourth style
    # added to the frontend without the choices tuple fails here, which is the
    # only place the two can be compared.
    settings_store.set_value(key="appearance.illustration_style", raw="motion")
    assert settings_store.get("appearance.illustration_style") == "motion"


def test_the_illustration_style_defaults_to_editorial_doodle():
    settings_store.clear(key="appearance.illustration_style")
    assert settings_store.get("appearance.illustration_style") == "doodle"


def test_the_appearance_endpoint_is_public(client):
    """The landing page and the login form need the style before anyone has
    signed in, so this one endpoint is deliberately unauthenticated — and
    returns exactly one string rather than the console's whole settings view."""
    settings_store.clear(key="appearance.illustration_style")
    resp = client.get("/api/v1/platform/appearance/")
    assert resp.status_code == 200
    assert resp.json() == {"illustration_style": "doodle"}


def test_the_appearance_endpoint_exposes_nothing_else(client):
    """An allowlist of one is easier to keep safe than a filter over
    everything — the console's settings view reports which secrets are
    configured, and none of that may leak to an anonymous request."""
    body = client.get("/api/v1/platform/appearance/").json()
    assert set(body) == {"illustration_style"}
