"""Self-service email verification: request, confirm, and the register hook."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.users.email_verification_models import EmailVerificationToken
from apps.users.services import email_verification as svc

User = get_user_model()
pytestmark = pytest.mark.django_db


def _make_user(email="verify.me@example.com", password="OldPassw0rd!!", *, verified=False):
    user = User.objects.create_user(email=email, password=password)
    user.is_verified = verified
    user.save(update_fields=["is_verified"])
    return user


def test_register_sends_a_verification_email(api_client, django_capture_on_commit_callbacks):
    from django.core import mail

    with django_capture_on_commit_callbacks(execute=True):
        res = api_client.post(
            "/api/v1/auth/register/",
            {"email": "new.owner@example.com", "password": "correct-horse-battery-1"},
            format="json",
        )
    assert res.status_code == 201
    user = User.objects.get(email="new.owner@example.com")
    assert user.is_verified is False
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]
    assert "verify-email?token=" in mail.outbox[0].body


def test_full_verify_flow(api_client):
    user = _make_user()
    token = svc.request_verification(user=user)
    assert token

    confirm = api_client.post("/api/v1/auth/email/verify/confirm/", {"token": token}, format="json")
    assert confirm.status_code == 200, confirm.data
    user.refresh_from_db()
    assert user.is_verified is True

    again = api_client.post("/api/v1/auth/email/verify/confirm/", {"token": token}, format="json")
    assert again.status_code == 400


def test_already_verified_issues_no_token():
    user = _make_user(verified=True)
    assert svc.request_verification(user=user) is None
    assert EmailVerificationToken.objects.filter(user=user).count() == 0


def test_resend_is_authenticated(api_client):
    res = api_client.post("/api/v1/auth/email/verify/", {}, format="json")
    assert res.status_code in (401, 403)


def test_me_exposes_verification_state(auth_client, user):
    res = auth_client.get("/api/v1/auth/me/")
    assert res.status_code == 200
    assert "is_verified" in res.data
    assert res.data["is_verified"] is False
