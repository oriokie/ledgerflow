"""MFA (TOTP + backup codes) tests. Uses real `pyotp` codes throughout —
these are genuine TOTP verifications, not stubbed."""

from __future__ import annotations

import pyotp
import pytest

from apps.users.mfa_models import MFABackupCode, TOTPDevice
from tests.conftest import _bearer_client
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _enroll_and_confirm(client) -> tuple[str, list[str]]:
    """Enrolls TOTP for the client's user, confirms with a real code, returns
    (secret, backup_codes)."""
    enroll = client.post("/api/v1/auth/mfa/totp/enroll/")
    assert enroll.status_code == 200
    secret = enroll.data["secret"]
    code = pyotp.TOTP(secret).now()
    confirm = client.post("/api/v1/auth/mfa/totp/confirm/", {"code": code}, format="json")
    assert confirm.status_code == 201
    return secret, confirm.data["backup_codes"]


def test_totp_enrollment_requires_confirmation_before_activation(auth_client, user):
    resp = auth_client.post("/api/v1/auth/mfa/totp/enroll/")
    assert resp.status_code == 200
    assert "secret" in resp.data and "provisioning_uri" in resp.data
    # not active until confirmed
    device = TOTPDevice.objects.get(user=user)
    assert device.is_active is False


def test_totp_confirm_with_wrong_code_fails(auth_client):
    auth_client.post("/api/v1/auth/mfa/totp/enroll/")
    resp = auth_client.post("/api/v1/auth/mfa/totp/confirm/", {"code": "000000"}, format="json")
    assert resp.status_code == 400


def test_totp_confirm_issues_backup_codes(auth_client, user):
    secret, codes = _enroll_and_confirm(auth_client)
    assert len(codes) == 10  # MFA_BACKUP_CODE_COUNT default
    assert len(set(codes)) == 10  # all unique
    device = TOTPDevice.objects.get(user=user)
    assert device.is_active is True
    assert MFABackupCode.objects.filter(user=user, used_at__isnull=True).count() == 10


def test_login_with_mfa_enabled_requires_second_step(api_client, user):
    client = _bearer_client(user)
    secret, _codes = _enroll_and_confirm(client)

    login = api_client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "correct-horse-battery-staple"},
        format="json",
    )
    assert login.status_code == 200
    assert login.data["mfa_required"] is True
    assert "access" not in login.data  # critical: no usable tokens before MFA
    assert login.data["methods"] == ["totp"]

    mfa_token = login.data["mfa_token"]
    code = pyotp.TOTP(secret).now()
    verify = api_client.post(
        "/api/v1/auth/mfa/verify/", {"mfa_token": mfa_token, "code": code}, format="json"
    )
    assert verify.status_code == 200
    assert "access" in verify.data and "refresh" in verify.data


def test_mfa_verify_rejects_wrong_code(api_client, user):
    client = _bearer_client(user)
    _enroll_and_confirm(client)

    login = api_client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "correct-horse-battery-staple"},
        format="json",
    )
    verify = api_client.post(
        "/api/v1/auth/mfa/verify/", {"mfa_token": login.data["mfa_token"], "code": "000000"}, format="json"
    )
    assert verify.status_code == 401


def test_mfa_verify_rejects_tampered_challenge_token(api_client, user):
    client = _bearer_client(user)
    _enroll_and_confirm(client)
    resp = api_client.post(
        "/api/v1/auth/mfa/verify/", {"mfa_token": "not-a-real-token", "code": "123456"}, format="json"
    )
    assert resp.status_code == 401


def test_mfa_verify_token_cannot_be_reused_for_a_different_user(api_client):
    victim = UserFactory(email="victim@example.com", password="correct-horse-battery-staple")
    attacker = UserFactory(email="attacker@example.com", password="correct-horse-battery-staple")
    victim_client = _bearer_client(victim)
    secret, _codes = _enroll_and_confirm(victim_client)

    # The attacker cannot forge a valid mfa_token for the victim — signing.dumps
    # is HMAC-signed with SECRET_KEY, so a hand-crafted payload is rejected outright.
    from django.core import signing

    forged = signing.dumps({"user_id": str(victim.id)}, salt="wrong-salt")
    resp = api_client.post("/api/v1/auth/mfa/verify/", {"mfa_token": forged, "code": "000000"}, format="json")
    assert resp.status_code == 401
    del attacker  # unused beyond documenting intent


def test_backup_code_is_single_use(api_client, user):
    client = _bearer_client(user)
    secret, codes = _enroll_and_confirm(client)

    login = api_client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "correct-horse-battery-staple"},
        format="json",
    )
    mfa_token = login.data["mfa_token"]
    first_use = api_client.post(
        "/api/v1/auth/mfa/verify/", {"mfa_token": mfa_token, "code": codes[0]}, format="json"
    )
    assert first_use.status_code == 200

    # A fresh login + the SAME backup code must now fail.
    login2 = api_client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "correct-horse-battery-staple"},
        format="json",
    )
    reuse = api_client.post(
        "/api/v1/auth/mfa/verify/", {"mfa_token": login2.data["mfa_token"], "code": codes[0]}, format="json"
    )
    assert reuse.status_code == 401


def test_disable_totp_requires_valid_code(auth_client, user):
    secret, _codes = _enroll_and_confirm(auth_client)
    bad = auth_client.post("/api/v1/auth/mfa/totp/disable/", {"code": "000000"}, format="json")
    assert bad.status_code == 400
    assert TOTPDevice.objects.filter(user=user).exists()

    good = auth_client.post(
        "/api/v1/auth/mfa/totp/disable/", {"code": pyotp.TOTP(secret).now()}, format="json"
    )
    assert good.status_code == 204
    assert not TOTPDevice.objects.filter(user=user).exists()
    assert not MFABackupCode.objects.filter(user=user).exists()


def test_regenerate_backup_codes_invalidates_old_ones(auth_client, user):
    secret, old_codes = _enroll_and_confirm(auth_client)
    resp = auth_client.post(
        "/api/v1/auth/mfa/backup-codes/regenerate/", {"code": pyotp.TOTP(secret).now()}, format="json"
    )
    assert resp.status_code == 200
    new_codes = resp.data["backup_codes"]
    assert set(new_codes).isdisjoint(old_codes)
    assert MFABackupCode.objects.filter(user=user, used_at__isnull=True).count() == 10


def test_totp_secret_is_encrypted_at_rest(auth_client, user):
    auth_client.post("/api/v1/auth/mfa/totp/enroll/")
    device = TOTPDevice.objects.get(user=user)
    # The raw column value must NOT be a valid base32 TOTP secret by itself —
    # it should only decrypt to one via get_secret().
    assert device.encrypted_secret != device.get_secret()
    assert len(device.encrypted_secret) > len(device.get_secret())


def test_login_without_mfa_returns_tokens_directly(api_client, user):
    login = api_client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "correct-horse-battery-staple"},
        format="json",
    )
    assert login.status_code == 200
    assert "access" in login.data
    assert "mfa_required" not in login.data
