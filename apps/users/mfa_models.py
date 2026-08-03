"""TOTP (RFC 6238) second factor + single-use backup codes.

The TOTP shared secret is genuinely sensitive: anyone who reads it can mint
valid codes forever (unlike a password hash, which is one-way). It's
encrypted at rest via `apps.common.crypto` rather than stored plaintext.
Backup codes are hashed with Django's own password hasher (Argon2) — they
function exactly like single-use passwords.
"""

from __future__ import annotations

import pyotp
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone

from apps.common.crypto import decrypt_str, encrypt_str
from apps.common.models import TimeStampedModel, UUIDModel


class TOTPDevice(UUIDModel, TimeStampedModel):
    """One per user. `confirmed_at IS NULL` means enrollment is in progress
    and the device is not yet usable to satisfy an MFA challenge — a code
    must be verified against it first (proves the secret was actually
    transferred to the user's authenticator app, not just generated)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="totp_device"
    )
    encrypted_secret = models.CharField(max_length=255)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_active(self) -> bool:
        return self.confirmed_at is not None

    @classmethod
    def generate_secret(cls) -> str:
        return pyotp.random_base32()

    def set_secret(self, raw_secret: str) -> None:
        self.encrypted_secret = encrypt_str(raw_secret)

    def get_secret(self) -> str:
        return decrypt_str(self.encrypted_secret)

    def provisioning_uri(self, *, account_name: str) -> str:
        issuer = getattr(settings, "MFA_ISSUER_NAME", "LedgerFlow")
        return pyotp.TOTP(self.get_secret()).provisioning_uri(name=account_name, issuer_name=issuer)

    def verify_code(self, code: str) -> bool:
        window = getattr(settings, "MFA_TOTP_VALID_WINDOW", 1)
        return pyotp.TOTP(self.get_secret()).verify(code, valid_window=window)


class MFABackupCode(UUIDModel, TimeStampedModel):
    """Single-use recovery codes issued in a batch when TOTP is confirmed
    (or explicitly regenerated). Each is consumed exactly once."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="backup_codes")
    code_hash = models.CharField(max_length=255)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user", "used_at"])]

    @classmethod
    def hash_code(cls, raw_code: str) -> str:
        return make_password(raw_code)

    def check_code(self, raw_code: str) -> bool:
        return self.used_at is None and check_password(raw_code, self.code_hash)

    def mark_used(self) -> None:
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])
