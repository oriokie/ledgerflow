"""Passkey (WebAuthn) tests. `SoftAuthenticator` performs real ECDSA P-256
signing; these tests prove the server-side verification logic is genuinely
correct, not that a mock was configured to return True."""

from __future__ import annotations

import pytest

from apps.users.webauthn_models import WebAuthnCredential
from tests.conftest import _bearer_client
from tests.factories import UserFactory
from tests.webauthn_fixtures import SoftAuthenticator

pytestmark = pytest.mark.django_db

RP_ID = "localhost"
ORIGIN = "http://localhost:3000"


@pytest.fixture(autouse=True)
def _webauthn_settings(settings):
    settings.WEBAUTHN_RP_ID = RP_ID
    settings.WEBAUTHN_ORIGINS = [ORIGIN]
    return settings


def _register_passkey(client, authenticator: SoftAuthenticator) -> dict:
    options = client.post("/api/v1/auth/webauthn/register/options/").data
    credential = authenticator.create_credential(challenge_b64url=options["challenge"])
    resp = client.post(
        "/api/v1/auth/webauthn/register/verify/",
        {"credential": credential, "device_name": "Test Authenticator"},
        format="json",
    )
    return resp


def test_register_passkey_end_to_end(auth_client, user):
    authenticator = SoftAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    resp = _register_passkey(auth_client, authenticator)
    assert resp.status_code == 201, resp.data
    assert resp.data["device_name"] == "Test Authenticator"
    assert WebAuthnCredential.objects.filter(user=user).count() == 1


def test_register_passkey_rejects_wrong_origin(auth_client):
    options = auth_client.post("/api/v1/auth/webauthn/register/options/").data
    evil_authenticator = SoftAuthenticator(rp_id=RP_ID, origin="https://evil.example.com")
    credential = evil_authenticator.create_credential(challenge_b64url=options["challenge"])
    resp = auth_client.post(
        "/api/v1/auth/webauthn/register/verify/", {"credential": credential}, format="json"
    )
    assert resp.status_code == 400


def test_register_passkey_rejects_replayed_challenge(auth_client):
    """A credential built for one challenge cannot be replayed against a
    second (already-consumed, single-use) challenge cache entry."""
    options = auth_client.post("/api/v1/auth/webauthn/register/options/").data
    authenticator = SoftAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    credential = authenticator.create_credential(challenge_b64url=options["challenge"])

    first = auth_client.post(
        "/api/v1/auth/webauthn/register/verify/", {"credential": credential}, format="json"
    )
    assert first.status_code == 201

    replay = auth_client.post(
        "/api/v1/auth/webauthn/register/verify/", {"credential": credential}, format="json"
    )
    assert replay.status_code == 400  # challenge was deleted after first use


def test_passwordless_login_with_passkey(api_client, user):
    owner_client = _bearer_client(user)
    authenticator = SoftAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    reg = _register_passkey(owner_client, authenticator)
    assert reg.status_code == 201

    options_resp = api_client.post(
        "/api/v1/auth/webauthn/authenticate/options/", {"email": user.email}, format="json"
    )
    assert options_resp.status_code == 200
    state = options_resp.data["state"]
    assertion = authenticator.get_assertion(challenge_b64url=options_resp.data["challenge"])

    verify_resp = api_client.post(
        "/api/v1/auth/webauthn/authenticate/verify/", {"state": state, "credential": assertion}, format="json"
    )
    assert verify_resp.status_code == 200, verify_resp.data
    assert "access" in verify_resp.data
    assert verify_resp.data["user"]["email"] == user.email


def test_passwordless_login_updates_sign_count(api_client, user):
    owner_client = _bearer_client(user)
    authenticator = SoftAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    _register_passkey(owner_client, authenticator)

    for _ in range(3):
        options_resp = api_client.post(
            "/api/v1/auth/webauthn/authenticate/options/", {"email": user.email}, format="json"
        )
        assertion = authenticator.get_assertion(challenge_b64url=options_resp.data["challenge"])
        resp = api_client.post(
            "/api/v1/auth/webauthn/authenticate/verify/",
            {"state": options_resp.data["state"], "credential": assertion},
            format="json",
        )
        assert resp.status_code == 200

    cred = WebAuthnCredential.objects.get(user=user)
    assert cred.sign_count == 3  # each successful auth increments it


def test_authentication_rejects_forged_signature(api_client, user):
    """A credential ID that matches a real registration, but signed by a
    DIFFERENT private key, must be rejected — this is the core security
    property of WebAuthn (possession of the private key), not just
    "did the credential ID look right"."""
    owner_client = _bearer_client(user)
    legit = SoftAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    _register_passkey(owner_client, legit)

    forger = SoftAuthenticator(rp_id=RP_ID, origin=ORIGIN, credential_id=legit.credential_id)

    options_resp = api_client.post(
        "/api/v1/auth/webauthn/authenticate/options/", {"email": user.email}, format="json"
    )
    forged_assertion = forger.get_assertion(challenge_b64url=options_resp.data["challenge"])

    resp = api_client.post(
        "/api/v1/auth/webauthn/authenticate/verify/",
        {"state": options_resp.data["state"], "credential": forged_assertion},
        format="json",
    )
    assert resp.status_code == 401


def test_clone_detection_rejects_stale_sign_count(api_client, user):
    owner_client = _bearer_client(user)
    authenticator = SoftAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    _register_passkey(owner_client, authenticator)

    # Genuine authentication brings sign_count to 5.
    options_resp = api_client.post(
        "/api/v1/auth/webauthn/authenticate/options/", {"email": user.email}, format="json"
    )
    assertion = authenticator.get_assertion(challenge_b64url=options_resp.data["challenge"], sign_count=5)
    ok = api_client.post(
        "/api/v1/auth/webauthn/authenticate/verify/",
        {"state": options_resp.data["state"], "credential": assertion},
        format="json",
    )
    assert ok.status_code == 200

    # A cloned authenticator replaying an OLDER counter value must be rejected.
    options_resp2 = api_client.post(
        "/api/v1/auth/webauthn/authenticate/options/", {"email": user.email}, format="json"
    )
    stale_assertion = authenticator.get_assertion(
        challenge_b64url=options_resp2.data["challenge"], sign_count=2
    )
    rejected = api_client.post(
        "/api/v1/auth/webauthn/authenticate/verify/",
        {"state": options_resp2.data["state"], "credential": stale_assertion},
        format="json",
    )
    assert rejected.status_code == 401


def test_passkey_login_bypasses_totp_requirement(api_client, user):
    """Passkey auth (with user verification) is a strong-enough factor on
    its own; TOTP still independently gates password login."""
    import pyotp

    owner_client = _bearer_client(user)
    authenticator = SoftAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    _register_passkey(owner_client, authenticator)

    enroll = owner_client.post("/api/v1/auth/mfa/totp/enroll/")
    code = pyotp.TOTP(enroll.data["secret"]).now()
    owner_client.post("/api/v1/auth/mfa/totp/confirm/", {"code": code}, format="json")

    login = api_client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "correct-horse-battery-staple"},
        format="json",
    )
    assert login.data["mfa_required"] is True
    assert set(login.data["methods"]) == {"totp", "webauthn"}

    options_resp = api_client.post(
        "/api/v1/auth/webauthn/authenticate/options/", {"email": user.email}, format="json"
    )
    assertion = authenticator.get_assertion(challenge_b64url=options_resp.data["challenge"])
    resp = api_client.post(
        "/api/v1/auth/webauthn/authenticate/verify/",
        {"state": options_resp.data["state"], "credential": assertion},
        format="json",
    )
    assert resp.status_code == 200
    assert "access" in resp.data


def test_manage_passkeys_list_and_delete(auth_client, user):
    authenticator = SoftAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    reg = _register_passkey(auth_client, authenticator)
    cred_id = reg.data["id"]

    listing = auth_client.get("/api/v1/auth/webauthn/credentials/")
    assert listing.status_code == 200
    assert len(listing.data) == 1

    delete = auth_client.delete(f"/api/v1/auth/webauthn/credentials/{cred_id}/")
    assert delete.status_code == 204
    assert WebAuthnCredential.objects.filter(user=user).count() == 0


def test_cannot_delete_another_users_passkey(auth_client):
    other = UserFactory(email="other@example.com")
    other_client = _bearer_client(other)
    authenticator = SoftAuthenticator(rp_id=RP_ID, origin=ORIGIN)
    reg = _register_passkey(other_client, authenticator)

    resp = auth_client.delete(f"/api/v1/auth/webauthn/credentials/{reg.data['id']}/")
    assert resp.status_code == 404
    assert WebAuthnCredential.objects.filter(user=other).count() == 1
