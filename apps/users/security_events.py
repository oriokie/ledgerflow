"""Authentication audit trail. Distinct from `apps.common.audit.AuditLog`
(tenant-scoped financial actions) — this is identity-layer security telemetry
and predates any tenant context, so `user` is nullable (an attempt against an
email with no matching account is still worth recording for abuse detection)."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import UUIDModel


class LoginMethod(models.TextChoices):
    PASSWORD = "password", "Password"
    OAUTH_GOOGLE = "oauth:google", "Google"
    OAUTH_APPLE = "oauth:apple", "Apple"
    WEBAUTHN = "webauthn", "Passkey"
    MFA_TOTP = "mfa_totp", "TOTP"
    MFA_BACKUP_CODE = "mfa_backup_code", "Backup code"


class LoginEvent(UUIDModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="login_events",
    )
    email_attempted = models.EmailField()
    method = models.CharField(max_length=32, choices=LoginMethod.choices)
    success = models.BooleanField()
    reason = models.CharField(
        max_length=64, blank=True, default=""
    )  # e.g. "invalid_password", "mfa_required"
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["email_attempted", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.method} {'ok' if self.success else 'fail'}: {self.email_attempted}"
