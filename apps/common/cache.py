"""Tenant-scoped caching for derived analytics.

Health scores, recommendations, anomaly scans and the like are expensive to
compute but change slowly and are read on every dashboard load. Caching them
cuts database load and response time — but in a multi-tenant system a cache
must never serve one tenant's data to another, and must invalidate the moment
that tenant's financial data changes.

Strategy: **version-stamped, tenant-scoped keys.**

    key = "ledgerflow:v{N}:{tenant}:{name}:{suffix}"

Each tenant has a monotonic version counter in the cache. Every cache key for
that tenant embeds the current version. To invalidate *everything* derived for
a tenant (after any posting/void/transfer/budget edit), we simply bump the
counter — old keys are instantly unreachable and expire on their own TTL. No
key enumeration, no scan, O(1) invalidation, and no risk of a stale key
lingering because we forgot to delete it.

Keys are always tenant-prefixed from `get_current_tenant_id()`, so a caller
physically cannot build a cross-tenant key.
"""

from __future__ import annotations

import functools
import hashlib
import json
from collections.abc import Callable

from django.core.cache import cache

from .tenant_context import get_current_tenant_id

_VERSION_TTL = 60 * 60 * 24 * 30  # version counters live 30d (refreshed on bump)


def _version_key(tenant_id: str) -> str:
    return f"ver:{tenant_id}"


def current_version(tenant_id: str) -> int:
    v = cache.get(_version_key(tenant_id))
    if v is None:
        v = 1
        cache.set(_version_key(tenant_id), v, _VERSION_TTL)
    return v


def invalidate_tenant(tenant_id=None) -> None:
    """Bump the tenant's cache version, instantly orphaning all its derived
    caches. Call after any write that changes financial state."""
    tenant_id = str(tenant_id or get_current_tenant_id())
    try:
        cache.incr(_version_key(tenant_id))
    except ValueError:
        # counter absent/expired — (re)seed it; next reads compute fresh
        cache.set(_version_key(tenant_id), current_version(tenant_id) + 1, _VERSION_TTL)


def _scoped_key(name: str, suffix: str = "") -> str:
    tenant_id = str(get_current_tenant_id())
    version = current_version(tenant_id)
    raw = f"v{version}:{tenant_id}:{name}:{suffix}"
    # hash the suffix portion to keep keys bounded and free of odd chars
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"analytics:{name}:{tenant_id}:v{version}:{digest}"


def cached_analytics(name: str, ttl: int = 300):
    """Decorator: cache a tenant-scoped, slow-changing analytic. The cache key
    includes the tenant, a per-tenant version (for O(1) invalidation), and a
    digest of the call arguments. TTL is a backstop; version-bump is the
    primary invalidation.

        @cached_analytics("health_score", ttl=300)
        def compute(...): ...
    """

    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # argument fingerprint (kwargs are the norm in this codebase)
            fingerprint = json.dumps(
                {"a": [str(a) for a in args], "k": {k: str(v) for k, v in kwargs.items()}},
                sort_keys=True,
            )
            key = _scoped_key(name, fingerprint)
            hit = cache.get(key)
            if hit is not None:
                return hit
            value = fn(*args, **kwargs)
            cache.set(key, value, ttl)
            return value

        return wrapper

    return decorator
