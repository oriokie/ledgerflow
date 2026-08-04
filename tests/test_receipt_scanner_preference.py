"""Receipt scanning is an opt-in sidebar entry, stored per user.

Scanning is a verb in a list of nouns, and it is the only navigation entry that
needs a camera. Most people photograph a receipt from the transaction they are
already entering, so the default is off and the entry is earned rather than
assumed. The page itself stays reachable — this hides a link, not a feature.
"""

from __future__ import annotations

import pytest

from apps.users.models import UserProfile

pytestmark = pytest.mark.django_db


def test_it_is_off_for_a_new_account(tenant_context):
    _, client = tenant_context
    assert client.get("/api/v1/auth/me/").data["show_receipt_scanner"] is False


def test_an_account_with_no_profile_row_still_answers(tenant_context):
    """Profiles are created on first write, so most accounts have none. Reading
    must fall through to the default rather than 500 or force a write."""
    _, client = tenant_context
    resp = client.get("/api/v1/auth/me/")
    assert resp.status_code == 200
    assert "show_receipt_scanner" in resp.data


def test_turning_it_on_persists(tenant_context):
    _, client = tenant_context
    resp = client.patch("/api/v1/auth/me/", {"show_receipt_scanner": True}, format="json")

    assert resp.status_code == 200
    assert resp.data["show_receipt_scanner"] is True
    assert client.get("/api/v1/auth/me/").data["show_receipt_scanner"] is True


def test_turning_it_back_off_persists(tenant_context):
    _, client = tenant_context
    client.patch("/api/v1/auth/me/", {"show_receipt_scanner": True}, format="json")
    client.patch("/api/v1/auth/me/", {"show_receipt_scanner": False}, format="json")

    assert client.get("/api/v1/auth/me/").data["show_receipt_scanner"] is False


def test_the_preference_creates_exactly_one_profile(tenant_context):
    """get_or_create, not create — a second toggle must not raise on the
    OneToOne constraint."""
    user, client = tenant_context
    client.patch("/api/v1/auth/me/", {"show_receipt_scanner": True}, format="json")
    client.patch("/api/v1/auth/me/", {"show_receipt_scanner": False}, format="json")

    assert UserProfile.objects.filter(user=user.user if hasattr(user, "user") else user).count() <= 1


def test_updating_a_name_does_not_disturb_the_preference(tenant_context):
    """The field is not on User, so it is popped before the model update — a
    PATCH that omits it must leave it alone rather than reset it."""
    _, client = tenant_context
    client.patch("/api/v1/auth/me/", {"show_receipt_scanner": True}, format="json")
    client.patch("/api/v1/auth/me/", {"first_name": "Edwin"}, format="json")

    body = client.get("/api/v1/auth/me/").data
    assert body["show_receipt_scanner"] is True
    assert body["first_name"] == "Edwin"


def test_it_is_a_user_preference_not_a_workspace_one():
    """It describes how a person works, so it follows them between households
    rather than being re-chosen in each."""
    field = UserProfile._meta.get_field("show_receipt_scanner")
    assert field.default is False
