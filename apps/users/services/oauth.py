"""OAuth2 / OIDC social login.

Deliberately hand-rolled against the standard authorization-code + PKCE flow
rather than a heavy SDK — this is a security-critical, small surface area
that's worth owning directly for audit purposes, and it keeps provider
config entirely data-driven (`settings.OAUTH_PROVIDERS`) so adding a new
provider is an env change, not a code change.

State + PKCE verifier are stored server-side (Redis) keyed by `state`, never
trusted from the client on callback — this is what makes the flow CSRF- and
interception-resistant.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from ..models import User
from ..oauth_models import SocialAccount

STATE_CACHE_PREFIX = "oauth:state:"
_REQUEST_TIMEOUT_SECONDS = 10


class OAuthError(Exception):
    pass


class UnknownProviderError(OAuthError):
    pass


class ProviderNotConfiguredError(OAuthError):
    pass


class InvalidStateError(OAuthError):
    pass


class ProviderExchangeError(OAuthError):
    """The provider rejected the code exchange or returned an unusable profile."""


class EmailAlreadyRegisteredError(OAuthError):
    """The provider's email matches an existing account, but the provider
    didn't assert it as verified — auto-linking would let anyone who
    controls that unverified address on the provider's side take over an
    existing LedgerFlow account. The user must log in normally and link the
    provider from their authenticated account settings instead."""


def _provider_config(provider: str) -> dict:
    providers = settings.OAUTH_PROVIDERS
    if provider not in providers:
        raise UnknownProviderError(f"Unknown OAuth provider: {provider!r}")
    config = dict(providers[provider])
    try:
        from apps.platform_admin.settings_store import get as store_get

        stored_id = store_get(f"oauth.{provider}.client_id")
        stored_secret = store_get(f"oauth.{provider}.client_secret")
        if stored_id:
            config["client_id"] = stored_id
        if stored_secret:
            config["client_secret"] = stored_secret
    except Exception:  # pragma: no cover — store unavailable must not take login down
        pass
    if not config.get("client_id") or not config.get("client_secret"):
        raise ProviderNotConfiguredError(f"OAuth provider {provider!r} is not configured.")
    return config


def _profile_from_id_token(id_token: str | None) -> dict | None:
    if not id_token or id_token.count(".") < 2:
        return None
    payload = id_token.split(".")[1]
    padded = payload + "=" * (-len(payload) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(claims, dict):
        return None
    return claims


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def build_authorization_url(provider: str) -> str:
    config = _provider_config(provider)
    state = secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()

    cache.set(
        f"{STATE_CACHE_PREFIX}{state}",
        {"provider": provider, "code_verifier": verifier},
        timeout=settings.OAUTH_STATE_TTL_SECONDS,
    )

    params = {
        "client_id": config["client_id"],
        "redirect_uri": settings.OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": config["scope"],
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    query = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    return f"{config['authorize_url']}?{query}"


def _exchange_code_for_userinfo(provider: str, config: dict, code: str, code_verifier: str) -> dict:
    try:
        token_resp = requests.post(
            config["token_url"],
            data={
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "code": code,
                "redirect_uri": settings.OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
    except requests.RequestException as exc:
        raise ProviderExchangeError(f"Token exchange with {provider} failed: {exc}") from exc

    access_token = token_data.get("access_token")
    if not access_token and not token_data.get("id_token"):
        raise ProviderExchangeError(f"{provider} did not return an access token.")

    if config.get("userinfo_url") and access_token:
        try:
            userinfo_resp = requests.get(
                config["userinfo_url"],
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            userinfo_resp.raise_for_status()
            return userinfo_resp.json()
        except requests.RequestException as exc:
            raise ProviderExchangeError(f"Fetching userinfo from {provider} failed: {exc}") from exc

    # Apple (and some OIDC providers) put identity in the id_token rather than
    # exposing a userinfo endpoint. The token arrived over HTTPS from the
    # provider's own token URL, so we decode the payload without a second hop.
    profile = _profile_from_id_token(token_data.get("id_token"))
    if profile:
        return profile
    raise ProviderExchangeError(f"{provider} userinfo endpoint is not configured.")


@transaction.atomic
def complete_oauth_login(*, state: str, code: str) -> tuple[User, bool]:
    """Returns (user, created). Links to an existing SocialAccount if one
    exists; otherwise links by verified email if a matching User already
    exists; otherwise creates a new User."""
    cached = cache.get(f"{STATE_CACHE_PREFIX}{state}")
    if cached is None:
        raise InvalidStateError("OAuth state is invalid or expired. Restart the login.")
    cache.delete(f"{STATE_CACHE_PREFIX}{state}")  # single-use

    provider = cached["provider"]
    config = _provider_config(provider)
    profile = _exchange_code_for_userinfo(provider, config, code, cached["code_verifier"])

    provider_user_id = profile.get("sub")
    email = (profile.get("email") or "").strip().lower()
    email_verified = bool(profile.get("email_verified", False))
    if not provider_user_id:
        raise ProviderExchangeError(f"{provider} profile is missing a stable subject id.")

    social = SocialAccount.objects.filter(provider=provider, provider_user_id=provider_user_id).first()
    if social is not None:
        return social.user, False

    user = None
    if email and email_verified:
        user = User.objects.filter(email=email).first()

    created = False
    if user is None:
        if not email:
            raise ProviderExchangeError(f"{provider} did not provide an email address.")
        if User.objects.filter(email=email).exists():
            # Email matches an existing account, but the provider did not
            # assert it as verified — refuse to auto-link (see
            # EmailAlreadyRegisteredError) rather than crash on the unique
            # constraint or silently take over the account.
            raise EmailAlreadyRegisteredError(
                f"An account with {email} already exists. Log in and link {provider} from account settings."
            )
        user = User.objects.create_user(email=email, password=None, is_verified=email_verified)
        created = True

    SocialAccount.objects.create(user=user, provider=provider, provider_user_id=provider_user_id, email=email)
    return user, created
