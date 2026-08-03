"""TOTP (RFC 6238) enrollment and verification."""

from __future__ import annotations

import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..mfa_models import MFABackupCode, TOTPDevice


class MFAError(Exception):
    pass


class MFAAlreadyEnabledError(MFAError):
    pass


class MFANotEnabledError(MFAError):
    pass


class InvalidCodeError(MFAError):
    pass


@transaction.atomic
def start_totp_enrollment(*, user) -> TOTPDevice:
    existing = TOTPDevice.objects.filter(user=user).first()
    if existing and existing.is_active:
        raise MFAAlreadyEnabledError("TOTP is already enabled. Disable it before re-enrolling.")
    if existing:
        existing.delete()  # replace a stale, never-confirmed enrollment attempt
    device = TOTPDevice(user=user)
    device.set_secret(TOTPDevice.generate_secret())
    device.save()
    return device


def _generate_backup_codes(*, user, count: int) -> list[str]:
    MFABackupCode.objects.filter(user=user, used_at__isnull=True).delete()  # invalidate old unused codes
    raw_codes = [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(count)]
    MFABackupCode.objects.bulk_create(
        [MFABackupCode(user=user, code_hash=MFABackupCode.hash_code(c)) for c in raw_codes]
    )
    return raw_codes


@transaction.atomic
def confirm_totp_enrollment(*, user, code: str) -> list[str]:
    device = TOTPDevice.objects.filter(user=user, confirmed_at__isnull=True).select_for_update().first()
    if device is None:
        raise MFANotEnabledError("No pending TOTP enrollment found.")
    if not device.verify_code(code):
        raise InvalidCodeError("Invalid verification code.")
    device.confirmed_at = timezone.now()
    device.save(update_fields=["confirmed_at"])
    return _generate_backup_codes(user=user, count=settings.MFA_BACKUP_CODE_COUNT)


@transaction.atomic
def disable_totp(*, user, code: str) -> None:
    """Requires a valid TOTP or backup code to disable — otherwise a hijacked
    session could strip MFA protection without ever proving possession of
    the second factor."""
    if verify_mfa_code(user=user, code=code) is None:
        raise InvalidCodeError("Invalid verification code.")
    TOTPDevice.objects.filter(user=user).delete()
    MFABackupCode.objects.filter(user=user).delete()


@transaction.atomic
def regenerate_backup_codes(*, user, code: str) -> list[str]:
    if verify_mfa_code(user=user, code=code) is None:
        raise InvalidCodeError("Invalid verification code.")
    return _generate_backup_codes(user=user, count=settings.MFA_BACKUP_CODE_COUNT)


def verify_mfa_code(*, user, code: str) -> str | None:
    """Tries TOTP first, then backup codes. Returns the method used ("mfa_totp"
    / "mfa_backup_code") or None if the code doesn't match either."""
    device = TOTPDevice.objects.filter(user=user, confirmed_at__isnull=False).first()
    if device and device.verify_code(code):
        device.last_used_at = timezone.now()
        device.save(update_fields=["last_used_at"])
        return "mfa_totp"

    for backup in MFABackupCode.objects.filter(user=user, used_at__isnull=True):
        if backup.check_code(code):
            backup.mark_used()
            return "mfa_backup_code"

    return None


def user_has_mfa_enabled(user) -> bool:
    return TOTPDevice.objects.filter(user=user, confirmed_at__isnull=False).exists()
