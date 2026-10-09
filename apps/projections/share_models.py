"""Shareable snapshots of a computed decision.

Not RLS-protected — same reasoning as `Invitation`: the recipient has no
workspace membership, so a public token lookup cannot run inside a tenant
session. Isolation is the hashed token, not a tenant bind. The payload is the
computed decision (verdict, figures, assumptions), never ledger rows.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel, UUIDModel


def _default_share_expiry():
    return timezone.now() + timedelta(days=getattr(settings, "DECISION_SHARE_TTL_DAYS", 7))


class DecisionShare(UUIDModel, TimeStampedModel):
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="decision_shares")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="decision_shares",
    )
    slug = models.SlugField(max_length=64)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    payload = models.JSONField()
    expires_at = models.DateTimeField(default=_default_share_expiry)

    class Meta:
        indexes = [models.Index(fields=["expires_at"])]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"decision-share:{self.slug}:{self.id}"

    @property
    def is_usable(self) -> bool:
        return self.expires_at > timezone.now()
