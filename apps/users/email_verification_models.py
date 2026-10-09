"""Single-use, time-limited email verification tokens.

Hashed at rest, same posture as password-reset tokens: a database leak must
not yield a working verify link.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class EmailVerificationToken(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_verification_tokens"
    )
    token_hash = models.CharField(max_length=64, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["token_hash", "used_at"])]

    def is_usable(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()
