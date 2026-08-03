"""WebAuthn (passkey) service layer.

Challenge state is ephemeral and correlator-based, stored in Redis (the
cache), never in a server-side session — the API is stateless JWT auth, so
there's no session to hang ceremony state off of. Registration ceremonies
(user already authenticated) key by user id; authentication ceremonies
(user not yet authenticated, possibly unknown) key by an opaque `state`
token returned to the client and echoed back on verification.
"""

from __future__ import annotations

import base64
import secrets

import webauthn
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json_dict
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from ..models import User
from ..webauthn_models import WebAuthnCredential

REG_CACHE_PREFIX = "webauthn:reg:"
AUTH_CACHE_PREFIX = "webauthn:auth:"


class WebAuthnError(Exception):
    pass


class ChallengeExpiredError(WebAuthnError):
    pass


class VerificationFailedError(WebAuthnError):
    pass


class CloneDetectedError(WebAuthnError):
    """Sign count went backwards — the credential may have been cloned."""


def _rp_id() -> str:
    return settings.WEBAUTHN_RP_ID


def _rp_name() -> str:
    return settings.WEBAUTHN_RP_NAME


def _origins() -> list[str]:
    return settings.WEBAUTHN_ORIGINS


def _ttl() -> int:
    return settings.WEBAUTHN_CHALLENGE_TTL_SECONDS


# ---------------------------------------------------------------------- registration
def build_registration_options(user: User) -> dict:
    existing = list(WebAuthnCredential.objects.filter(user=user).values_list("credential_id", flat=True))
    options = webauthn.generate_registration_options(
        rp_id=_rp_id(),
        rp_name=_rp_name(),
        user_id=user.id.bytes,
        user_name=user.email,
        user_display_name=user.full_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(cid)) for cid in existing],
    )
    cache.set(f"{REG_CACHE_PREFIX}{user.id}", bytes_to_base64url(options.challenge), timeout=_ttl())
    return options_to_json_dict(options)


def verify_registration(*, user: User, credential: dict, device_name: str = "") -> WebAuthnCredential:
    cache_key = f"{REG_CACHE_PREFIX}{user.id}"
    challenge_b64 = cache.get(cache_key)
    if challenge_b64 is None:
        raise ChallengeExpiredError(
            "Registration challenge expired or was never issued. Request new options first."
        )

    try:
        verification = webauthn.verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_rp_id=_rp_id(),
            expected_origin=_origins(),
        )
    except InvalidRegistrationResponse as exc:
        raise VerificationFailedError(str(exc)) from exc
    finally:
        cache.delete(cache_key)  # challenge is single-use regardless of outcome

    transports = credential.get("response", {}).get("transports", []) if isinstance(credential, dict) else []

    return WebAuthnCredential.objects.create(
        user=user,
        credential_id=bytes_to_base64url(verification.credential_id),
        public_key=base64.b64encode(verification.credential_public_key).decode(),
        sign_count=verification.sign_count,
        transports=transports,
        aaguid=verification.aaguid,
        device_name=device_name,
        backup_eligible=verification.credential_backed_up,
        backup_state=verification.credential_backed_up,
    )


# ---------------------------------------------------------------------- authentication
def build_authentication_options(email: str | None = None) -> tuple[dict, str]:
    """Returns (options_json, state_token). If `email` matches a user with
    passkeys, `allow_credentials` is constrained to theirs; otherwise this is
    a "discoverable credential" (usernameless) ceremony and the platform
    authenticator picks from any resident key it holds for this RP."""
    allow_credentials = None
    known_user_id = None
    if email:
        user = User.objects.filter(email=email.strip().lower()).first()
        if user is not None:
            known_user_id = str(user.id)
            creds = list(WebAuthnCredential.objects.filter(user=user).values_list("credential_id", flat=True))
            allow_credentials = [PublicKeyCredentialDescriptor(id=base64url_to_bytes(c)) for c in creds]

    options = webauthn.generate_authentication_options(
        rp_id=_rp_id(),
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    state_token = secrets.token_urlsafe(24)
    cache.set(
        f"{AUTH_CACHE_PREFIX}{state_token}",
        {"challenge": bytes_to_base64url(options.challenge), "user_id": known_user_id},
        timeout=_ttl(),
    )
    return options_to_json_dict(options), state_token


def verify_authentication(*, state_token: str, credential: dict) -> User:
    cache_key = f"{AUTH_CACHE_PREFIX}{state_token}"
    state = cache.get(cache_key)
    if state is None:
        raise ChallengeExpiredError(
            "Authentication challenge expired or is invalid. Request new options first."
        )
    cache.delete(cache_key)  # single-use regardless of outcome

    raw_id = credential.get("rawId") or credential.get("id") if isinstance(credential, dict) else None
    if not raw_id:
        raise VerificationFailedError("Malformed credential response.")
    cred_id_b64url = bytes_to_base64url(base64url_to_bytes(raw_id))

    stored = WebAuthnCredential.objects.filter(credential_id=cred_id_b64url).select_related("user").first()
    if stored is None:
        raise VerificationFailedError("This passkey is not registered.")
    if state["user_id"] and str(stored.user_id) != state["user_id"]:
        raise VerificationFailedError("Passkey does not belong to the expected account.")

    try:
        verification = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(state["challenge"]),
            expected_rp_id=_rp_id(),
            expected_origin=_origins(),
            credential_public_key=base64.b64decode(stored.public_key),
            credential_current_sign_count=stored.sign_count,
        )
    except InvalidAuthenticationResponse as exc:
        raise VerificationFailedError(str(exc)) from exc

    # Clone detection: a real authenticator's counter only increases. A
    # persistently-zero counter (common for synced/platform passkeys) is
    # normal and not flagged; any *decrease* from a nonzero value is not.
    if stored.sign_count != 0 and verification.new_sign_count <= stored.sign_count:
        raise CloneDetectedError(
            f"Sign count did not increase ({stored.sign_count} -> {verification.new_sign_count}); "
            "this credential may have been cloned."
        )

    stored.sign_count = verification.new_sign_count
    stored.last_used_at = timezone.now()
    stored.backup_state = verification.credential_backed_up
    stored.save(update_fields=["sign_count", "last_used_at", "backup_state"])
    return stored.user
