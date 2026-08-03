"""OAuth/social login tests.

We can't do a live round-trip against real Google/Apple (no real client
credentials exist in this environment), so provider HTTP calls are mocked —
but PKCE generation, state storage/validation, single-use enforcement, and
account linking logic are all real and exercised end-to-end through the
actual service layer and API endpoints.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.cache import cache

from apps.users.models import User
from apps.users.oauth_models import SocialAccount
from apps.users.services import oauth as oauth_service
from tests.conftest import _bearer_client
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _oauth_settings(settings):
    settings.OAUTH_PROVIDERS = {
        "google": {
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
            "scope": "openid email profile",
        },
        "unconfigured": {
            "client_id": "",
            "client_secret": "",
            "authorize_url": "",
            "token_url": "",
            "userinfo_url": "",
            "scope": "",
        },
    }
    settings.OAUTH_REDIRECT_URI = "http://localhost:3000/auth/callback"
    return settings


def _mock_provider_responses(*, sub="google-sub-1", email="alice@example.com", email_verified=True):
    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    def fake_post(url, **kwargs):
        assert url == "https://oauth2.googleapis.com/token"
        assert kwargs["data"]["grant_type"] == "authorization_code"
        assert "code_verifier" in kwargs["data"]  # PKCE verifier really is sent
        return _Resp({"access_token": "fake-access-token"})

    def fake_get(url, **kwargs):
        assert url == "https://openidconnect.googleapis.com/v1/userinfo"
        assert kwargs["headers"]["Authorization"] == "Bearer fake-access-token"
        return _Resp({"sub": sub, "email": email, "email_verified": email_verified})

    return fake_post, fake_get


def test_authorize_url_contains_pkce_and_state():
    url = oauth_service.build_authorization_url("google")
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url
    assert "state=" in url
    assert "client_id=test-client-id" in url


def test_authorize_unconfigured_provider_raises():
    with pytest.raises(oauth_service.ProviderNotConfiguredError):
        oauth_service.build_authorization_url("unconfigured")


def test_authorize_unknown_provider_raises():
    with pytest.raises(oauth_service.UnknownProviderError):
        oauth_service.build_authorization_url("not-a-real-provider")


def test_callback_creates_new_user_and_links_social_account():
    url = oauth_service.build_authorization_url("google")
    state = url.split("state=")[1].split("&")[0]

    fake_post, fake_get = _mock_provider_responses(email="brandnew@example.com")
    with patch("requests.post", side_effect=fake_post), patch("requests.get", side_effect=fake_get):
        user, created = oauth_service.complete_oauth_login(state=state, code="auth-code-123")

    assert created is True
    assert user.email == "brandnew@example.com"
    assert user.is_verified is True
    assert SocialAccount.objects.filter(
        user=user, provider="google", provider_user_id="google-sub-1"
    ).exists()


def test_callback_links_to_existing_user_by_verified_email():
    existing = UserFactory(email="existing@example.com")
    url = oauth_service.build_authorization_url("google")
    state = url.split("state=")[1].split("&")[0]

    fake_post, fake_get = _mock_provider_responses(email="existing@example.com", email_verified=True)
    with patch("requests.post", side_effect=fake_post), patch("requests.get", side_effect=fake_get):
        user, created = oauth_service.complete_oauth_login(state=state, code="auth-code-123")

    assert created is False
    assert user.id == existing.id


def test_callback_does_not_link_unverified_email_to_existing_account():
    """An unverified email claim from the provider must NOT let an attacker
    take over an existing account just by claiming its address — and must
    NOT silently create a duplicate (impossible anyway: email is globally
    unique) or crash. It must be cleanly rejected."""
    victim = UserFactory(email="victim@example.com")
    url = oauth_service.build_authorization_url("google")
    state = url.split("state=")[1].split("&")[0]

    fake_post, fake_get = _mock_provider_responses(email="victim@example.com", email_verified=False)
    with (
        patch("requests.post", side_effect=fake_post),
        patch("requests.get", side_effect=fake_get),
        pytest.raises(oauth_service.EmailAlreadyRegisteredError),
    ):
        oauth_service.complete_oauth_login(state=state, code="auth-code-123")

    # No SocialAccount was created, and the victim's account is untouched.
    assert not SocialAccount.objects.filter(provider_user_id="google-sub-1").exists()
    assert User.objects.filter(email="victim@example.com").count() == 1
    del victim


def test_callback_rejects_reused_state():
    url = oauth_service.build_authorization_url("google")
    state = url.split("state=")[1].split("&")[0]

    fake_post, fake_get = _mock_provider_responses()
    with patch("requests.post", side_effect=fake_post), patch("requests.get", side_effect=fake_get):
        oauth_service.complete_oauth_login(state=state, code="auth-code-123")

    with pytest.raises(oauth_service.InvalidStateError):
        oauth_service.complete_oauth_login(state=state, code="auth-code-123")


def test_callback_rejects_unknown_state():
    with pytest.raises(oauth_service.InvalidStateError):
        oauth_service.complete_oauth_login(state="totally-made-up-state", code="whatever")


def test_second_login_with_same_provider_account_does_not_duplicate_user():
    url1 = oauth_service.build_authorization_url("google")
    state1 = url1.split("state=")[1].split("&")[0]
    fake_post, fake_get = _mock_provider_responses(sub="stable-sub", email="repeat@example.com")
    with patch("requests.post", side_effect=fake_post), patch("requests.get", side_effect=fake_get):
        user1, created1 = oauth_service.complete_oauth_login(state=state1, code="code-1")

    url2 = oauth_service.build_authorization_url("google")
    state2 = url2.split("state=")[1].split("&")[0]
    with patch("requests.post", side_effect=fake_post), patch("requests.get", side_effect=fake_get):
        user2, created2 = oauth_service.complete_oauth_login(state=state2, code="code-2")

    assert created1 is True
    assert created2 is False
    assert user1.id == user2.id
    assert User.objects.filter(email="repeat@example.com").count() == 1


def test_oauth_api_endpoints_end_to_end(api_client):
    authorize = api_client.get("/api/v1/auth/oauth/google/authorize/")
    assert authorize.status_code == 200
    state = authorize.data["authorization_url"].split("state=")[1].split("&")[0]

    fake_post, fake_get = _mock_provider_responses(email="viaapi@example.com")
    with patch("requests.post", side_effect=fake_post), patch("requests.get", side_effect=fake_get):
        callback = api_client.post(
            "/api/v1/auth/oauth/google/callback/", {"state": state, "code": "auth-code"}, format="json"
        )
    assert callback.status_code == 200
    assert "access" in callback.data
    assert callback.data["user"]["email"] == "viaapi@example.com"


def test_oauth_login_still_gates_on_existing_mfa(api_client):
    import pyotp

    existing = UserFactory(email="mfauser@example.com")
    owner_client = _bearer_client(existing)
    enroll = owner_client.post("/api/v1/auth/mfa/totp/enroll/")
    code = pyotp.TOTP(enroll.data["secret"]).now()
    owner_client.post("/api/v1/auth/mfa/totp/confirm/", {"code": code}, format="json")

    url = oauth_service.build_authorization_url("google")
    state = url.split("state=")[1].split("&")[0]
    fake_post, fake_get = _mock_provider_responses(email="mfauser@example.com", email_verified=True)
    with patch("requests.post", side_effect=fake_post), patch("requests.get", side_effect=fake_get):
        resp = api_client.post(
            "/api/v1/auth/oauth/google/callback/", {"state": state, "code": "auth-code"}, format="json"
        )
    assert resp.status_code == 200
    assert resp.data["mfa_required"] is True
    assert "access" not in resp.data


def test_authorize_url_state_expires(settings):
    settings.OAUTH_STATE_TTL_SECONDS = 600
    url = oauth_service.build_authorization_url("google")
    state = url.split("state=")[1].split("&")[0]
    assert cache.get(f"oauth:state:{state}") is not None
    cache.delete(f"oauth:state:{state}")  # simulate expiry
    with pytest.raises(oauth_service.InvalidStateError):
        oauth_service.complete_oauth_login(state=state, code="whatever")
