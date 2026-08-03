"""Login orchestration.

The core rule: a user with a confirmed MFA method never gets real tokens
from a password check alone. `authenticate_with_password` raises
`MFARequiredError` carrying a short-lived, stateless *challenge* token (NOT
an access token — it authorizes nothing except a call to
`resolve_mfa_challenge`) that the client exchanges for real tokens after
completing the second factor. The challenge token is a signed
(`django.core.signing`), timestamped payload — no DB row needed, so it works
identically across any number of API replicas without shared session state.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import authenticate
from django.core import signing
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from ..mfa_models import TOTPDevice
from ..models import User
from ..webauthn_models import WebAuthnCredential

MFA_SIGNING_SALT = "users.mfa_challenge"  # noqa: S105 — a signing salt, not a secret


class LoginError(Exception):
    pass


class InvalidCredentialsError(LoginError):
    pass


class MFARequiredError(LoginError):
    def __init__(self, mfa_token: str, methods: list[str]):
        self.mfa_token = mfa_token
        self.methods = methods
        super().__init__("MFA verification required.")


def issue_mfa_challenge(user: User) -> str:
    return signing.dumps({"user_id": str(user.id)}, salt=MFA_SIGNING_SALT)


def resolve_mfa_challenge(mfa_token: str) -> User:
    try:
        payload = signing.loads(mfa_token, salt=MFA_SIGNING_SALT, max_age=settings.MFA_CHALLENGE_TTL_SECONDS)
    except signing.BadSignature as exc:
        raise InvalidCredentialsError("Invalid or expired MFA challenge.") from exc
    user = User.objects.filter(id=payload["user_id"], is_active=True).first()
    if user is None:
        raise InvalidCredentialsError("Invalid or expired MFA challenge.")
    return user


def authenticate_with_password(*, email: str, password: str, request=None) -> User:
    """Returns a User on fully-authenticated success. Raises
    `MFARequiredError` if a second factor is still needed, or
    `InvalidCredentialsError` on bad credentials — deliberately the SAME
    exception whether the email doesn't exist or the password is wrong, to
    avoid leaking account existence via response differences."""
    user = authenticate(request=request, username=email.strip().lower(), password=password)
    if user is None or not user.is_active:
        raise InvalidCredentialsError("Invalid email or password.")

    if TOTPDevice.objects.filter(user=user, confirmed_at__isnull=False).exists():
        methods = ["totp"]
        if WebAuthnCredential.objects.filter(user=user).exists():
            methods.append("webauthn")
        raise MFARequiredError(mfa_token=issue_mfa_challenge(user), methods=methods)
    return user


def issue_tokens(*, user: User, request=None) -> dict:
    refresh = RefreshToken.for_user(user)
    user.last_login_at = timezone.now()
    if request is not None:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        user.last_login_ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    user.save(update_fields=["last_login_at", "last_login_ip"])
    return {"access": str(refresh.access_token), "refresh": str(refresh)}
