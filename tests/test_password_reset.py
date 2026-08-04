"""Recovery journey: forgot password → reset link → set new password → sign in."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.users.password_reset_models import PasswordResetToken
from apps.users.services import password_reset as svc

User = get_user_model()
pytestmark = pytest.mark.django_db


def _make_user(email="reset.me@example.com", password="OldPassw0rd!!"):
    return User.objects.create_user(email=email, password=password)


def test_request_is_silent_for_unknown_email(api_client):
    res = api_client.post("/api/v1/auth/password/reset/", {"email": "nobody@example.com"}, format="json")
    assert res.status_code == 200
    # No token created, and the response doesn't reveal non-existence.
    assert PasswordResetToken.objects.count() == 0
    assert "reset link is on its way" in res.data["detail"]


def test_full_reset_flow(api_client):
    user = _make_user()
    # The request endpoint responds 200 without leaking the token (DEBUG is off
    # in tests); obtain the raw token via the service, as an email worker would.
    req = api_client.post("/api/v1/auth/password/reset/", {"email": user.email}, format="json")
    assert req.status_code == 200
    assert "debug_token" not in req.data
    token = svc.request_password_reset(email=user.email)

    new_password = "BrandNewPass9$x"
    confirm = api_client.post(
        "/api/v1/auth/password/reset/confirm/",
        {"token": token, "new_password": new_password},
        format="json",
    )
    assert confirm.status_code == 200, confirm.data

    user.refresh_from_db()
    assert user.check_password(new_password)
    # Token is single-use.
    again = api_client.post(
        "/api/v1/auth/password/reset/confirm/",
        {"token": token, "new_password": "AnotherPass9$x"},
        format="json",
    )
    assert again.status_code == 400


def test_requesting_again_invalidates_the_previous_token(api_client):
    user = _make_user()
    first = svc.request_password_reset(email=user.email)
    svc.request_password_reset(email=user.email)  # supersedes the first
    # The first (now superseded) token no longer works.
    res = api_client.post(
        "/api/v1/auth/password/reset/confirm/",
        {"token": first, "new_password": "BrandNewPass9$x"},
        format="json",
    )
    assert res.status_code == 400


def test_weak_password_is_rejected(api_client):
    user = _make_user()
    token = svc.request_password_reset(email=user.email)
    res = api_client.post(
        "/api/v1/auth/password/reset/confirm/",
        {"token": token, "new_password": "short"},
        format="json",
    )
    assert res.status_code == 400


def test_expired_token_is_rejected():
    from datetime import timedelta

    from django.utils import timezone

    user = _make_user()
    raw = svc.request_password_reset(email=user.email)
    PasswordResetToken.objects.filter(user=user).update(expires_at=timezone.now() - timedelta(minutes=1))
    with pytest.raises(svc.InvalidResetToken):
        svc.reset_password(raw_token=raw, new_password="BrandNewPass9$x")
