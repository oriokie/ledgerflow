"""WebAuthn / passkey credentials.

Stores what the spec calls the "public key credential source" minus the
private key, which never leaves the authenticator. `sign_count` is the clone-
detection mechanism: a genuine authenticator's counter only increases: if a
verification arrives with a count <= what we have on file, either the
counter isn't implemented (common for platform authenticators using
discoverable/synced passkeys, which may report 0 forever) or the credential
was cloned. We treat a persistently-zero counter as normal (many passkey
implementations do this) but reject any *decrease* from a nonzero value.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


class WebAuthnCredential(UUIDModel, TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="webauthn_credentials"
    )
    credential_id = models.CharField(max_length=1024, unique=True)  # base64url
    public_key = models.TextField()  # base64-encoded COSE key bytes
    sign_count = models.BigIntegerField(default=0)
    transports = models.JSONField(default=list, blank=True)  # e.g. ["internal", "hybrid"]
    aaguid = models.CharField(max_length=64, blank=True, default="")
    device_name = models.CharField(max_length=100, blank=True, default="")
    backup_eligible = models.BooleanField(default=False)  # credential CAN be synced (e.g. iCloud Keychain)
    backup_state = models.BooleanField(default=False)  # credential IS currently backed up/synced
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["user"])]

    def __str__(self) -> str:
        return self.device_name or f"passkey:{self.credential_id[:12]}"
