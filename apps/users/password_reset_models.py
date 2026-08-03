"""Single-use, time-limited password reset tokens.

Only the SHA-256 hash of the token is stored, mirroring how invitation tokens
are handled — a database leak must not yield usable reset links. Tokens are
invalidated on use and expire after a short window.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class PasswordResetToken(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="password_reset_tokens"
    )
    token_hash = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["token_hash", "used_at"])]

    def is_usable(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()

    def __str__(self) -> str:
        return f"password-reset:{self.user_id}"
