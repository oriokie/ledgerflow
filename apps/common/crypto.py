"""Field-level encryption for secrets that must never be readable from a DB
dump alone (TOTP shared secrets). Uses Fernet (AES-128-CBC + HMAC), keyed by
`FIELD_ENCRYPTION_KEY` — deliberately NOT `SECRET_KEY`, so rotating one never
silently corrupts the other's data.

This is encryption-at-rest for a specific sensitive column, not a general
KMS. For production, `FIELD_ENCRYPTION_KEY` should come from a real secrets
manager (AWS Secrets Manager / GCP Secret Manager / Vault), not plain env.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class DecryptionError(Exception):
    pass


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
    if not key:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY is not set. Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_str(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_str(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError("Ciphertext is invalid or was encrypted with a different key.") from exc
