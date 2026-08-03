from __future__ import annotations

import pytest

from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_register_creates_user(api_client):
    resp = api_client.post(
        "/api/v1/auth/register/",
        {
            "email": "new@example.com",
            "password": "correct-horse-battery-1",
        },
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["email"] == "new@example.com"
    assert "password" not in resp.data


def test_register_rejects_duplicate_email(api_client):
    UserFactory(email="taken@example.com")
    resp = api_client.post(
        "/api/v1/auth/register/",
        {
            "email": "taken@example.com",
            "password": "correct-horse-battery-1",
        },
        format="json",
    )
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "invalid"


def test_register_rejects_weak_password(api_client):
    resp = api_client.post(
        "/api/v1/auth/register/",
        {
            "email": "weak@example.com",
            "password": "short",
        },
        format="json",
    )
    assert resp.status_code == 400


def test_login_returns_tokens_and_stamps_last_login(api_client):
    UserFactory(email="alice@example.com", password="correct-horse-battery-1")
    resp = api_client.post(
        "/api/v1/auth/login/",
        {
            "email": "alice@example.com",
            "password": "correct-horse-battery-1",
        },
        format="json",
    )
    assert resp.status_code == 200
    assert "access" in resp.data and "refresh" in resp.data
    assert resp.data["user"]["email"] == "alice@example.com"


def test_login_rejects_wrong_password(api_client):
    UserFactory(email="alice@example.com", password="correct-horse-battery-1")
    resp = api_client.post(
        "/api/v1/auth/login/",
        {
            "email": "alice@example.com",
            "password": "wrong-password",
        },
        format="json",
    )
    assert resp.status_code == 401


def test_me_requires_authentication(api_client):
    resp = api_client.get("/api/v1/auth/me/")
    assert resp.status_code == 401


def test_me_returns_current_user(auth_client, user):
    resp = auth_client.get("/api/v1/auth/me/")
    assert resp.status_code == 200
    assert resp.data["id"] == str(user.id)


def test_refresh_rotates_and_blacklists_old_token(api_client):
    UserFactory(email="alice@example.com", password="correct-horse-battery-1")
    login = api_client.post(
        "/api/v1/auth/login/",
        {
            "email": "alice@example.com",
            "password": "correct-horse-battery-1",
        },
        format="json",
    )
    old_refresh = login.data["refresh"]

    first_refresh = api_client.post("/api/v1/auth/refresh/", {"refresh": old_refresh}, format="json")
    assert first_refresh.status_code == 200

    replay = api_client.post("/api/v1/auth/refresh/", {"refresh": old_refresh}, format="json")
    assert replay.status_code == 401  # rotated tokens can't be reused


def test_logout_blacklists_refresh_token(api_client, auth_client):
    UserFactory(email="alice@example.com", password="correct-horse-battery-1")
    login = api_client.post(
        "/api/v1/auth/login/",
        {
            "email": "alice@example.com",
            "password": "correct-horse-battery-1",
        },
        format="json",
    )
    access, refresh = login.data["access"], login.data["refresh"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    logout = api_client.post("/api/v1/auth/logout/", {"refresh": refresh}, format="json")
    assert logout.status_code == 204

    reuse = api_client.post("/api/v1/auth/refresh/", {"refresh": refresh}, format="json")
    assert reuse.status_code == 401
