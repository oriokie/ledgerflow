"""OAuth / social login — a user may link several providers to one account."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


class SocialAccount(UUIDModel, TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="social_accounts"
    )
    provider = models.CharField(max_length=32)  # "google", "apple", ...
    provider_user_id = models.CharField(max_length=255)  # the provider's stable `sub` claim
    email = models.EmailField(blank=True, default="")  # as reported by the provider, for reference only

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "provider_user_id"], name="uniq_provider_account"),
        ]
        indexes = [models.Index(fields=["user", "provider"])]

    def __str__(self) -> str:
        return f"{self.provider}:{self.provider_user_id}"
