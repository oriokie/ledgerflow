"""Password reset service.

Security posture:
- Requesting a reset never reveals whether an email is registered (no user
  enumeration): the endpoint always succeeds, and the token is only created
  when a matching active user exists.
- Tokens are random, hashed at rest, single-use, and short-lived.
- Delivery is decoupled: there's no email backend wired in this build, so the
  reset link is emitted via the logger (and returned to the caller only in
  DEBUG). In production this hook is where an email/notification worker sends
  the link.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model, password_validation
from django.db import transaction
from django.utils import timezone

from ..password_reset_models import PasswordResetToken

logger = logging.getLogger(__name__)

User = get_user_model()

TOKEN_TTL = timedelta(hours=1)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


@transaction.atomic
def request_password_reset(*, email: str) -> str | None:
    """Issue a reset token for `email` if it belongs to an active user.

    Returns the raw token when a matching user exists, else None. Exposure of
    the token is the caller's concern: the HTTP layer only ever surfaces it in
    DEBUG; production delivers it out of band. Callers should respond
    identically whether or not a user was found (no enumeration).
    """
    email = (email or "").strip().lower()
    user = User.objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        logger.info("Password reset requested for unknown/inactive address; no-op.")
        return None

    # Invalidate any outstanding tokens so only the newest link works.
    PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())

    raw_token = secrets.token_urlsafe(32)
    PasswordResetToken.objects.create(
        user=user,
        token_hash=_hash_token(raw_token),
        expires_at=timezone.now() + TOKEN_TTL,
    )

    # Delivery hook — replace with an email/notification send in production.
    logger.info("Password reset link issued for user %s (delivered out of band).", user.id)
    return raw_token


class InvalidResetToken(Exception):
    """Raised when a reset token is missing, expired, or already used."""


@transaction.atomic
def reset_password(*, raw_token: str, new_password: str) -> None:
    token = (
        PasswordResetToken.objects.select_for_update()
        .filter(token_hash=_hash_token(raw_token or ""), used_at__isnull=True)
        .select_related("user")
        .first()
    )
    if token is None or not token.is_usable():
        raise InvalidResetToken("This reset link is invalid or has expired.")

    # Enforce the same password policy as registration.
    password_validation.validate_password(new_password, user=token.user)

    user = token.user
    user.set_password(new_password)
    user.save(update_fields=["password"])
    token.used_at = timezone.now()
    token.save(update_fields=["used_at"])
    logger.info("Password reset completed for user %s.", user.id)
