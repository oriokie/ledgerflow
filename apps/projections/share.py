"""Create and resolve hashed decision-share tokens.

The raw token is returned to the creator exactly once and never stored — only
its SHA-256, the same at-rest discipline as invitations and password-reset
tokens. A leaked database dump is not enough to open someone else's take-home.
"""

from __future__ import annotations

import hashlib
import secrets

from apps.tenancy.models import Tenant

from .share_models import DecisionShare


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_share(*, tenant_id, created_by, slug: str, payload: dict) -> tuple[str, DecisionShare]:
    raw_token = secrets.token_urlsafe(32)
    share = DecisionShare.objects.create(
        tenant=Tenant.objects.get(pk=tenant_id),
        created_by=created_by,
        slug=slug,
        payload=payload,
        token_hash=_hash_token(raw_token),
    )
    return raw_token, share


def get_usable_share(raw_token: str) -> DecisionShare | None:
    if not raw_token:
        return None
    share = DecisionShare.objects.filter(token_hash=_hash_token(raw_token)).first()
    if share is None or not share.is_usable:
        return None
    return share
