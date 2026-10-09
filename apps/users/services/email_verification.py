"""Issue and consume email-verification tokens."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from ..email_verification_models import EmailVerificationToken

logger = logging.getLogger(__name__)
User = get_user_model()
TOKEN_TTL = timedelta(hours=24)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


@transaction.atomic
def request_verification(*, user) -> str | None:
    """Issue a verify token for an unverified account. None if already verified."""
    if user.is_verified:
        return None
    EmailVerificationToken.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())
    raw_token = secrets.token_urlsafe(32)
    EmailVerificationToken.objects.create(
        user=user,
        token_hash=_hash_token(raw_token),
        expires_at=timezone.now() + TOKEN_TTL,
    )
    user_id = str(user.id)

    def _dispatch() -> None:
        from ..tasks import send_email_verification

        send_email_verification.delay(user_id=user_id, raw_token=raw_token)

    transaction.on_commit(_dispatch)
    return raw_token


class InvalidVerificationToken(Exception):
    pass


@transaction.atomic
def confirm_verification(*, raw_token: str):
    token = (
        EmailVerificationToken.objects.select_for_update()
        .filter(token_hash=_hash_token(raw_token or ""), used_at__isnull=True)
        .select_related("user")
        .first()
    )
    if token is None or not token.is_usable():
        raise InvalidVerificationToken("This verification link is invalid or has expired.")
    user = token.user
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    token.used_at = timezone.now()
    token.save(update_fields=["used_at"])
    return user
