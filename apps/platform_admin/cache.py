"""Caching for platform-wide aggregates.

`apps.common.cache.cached_analytics` cannot be reused here: its key is built
from `get_current_tenant_id()`, and platform metrics run with no tenant bound
— by design, since binding one would scope the very cross-tenant query the
dashboard exists to make. Calling it from here would raise.

The invalidation strategy also differs. Tenant analytics use a version counter
bumped on every write, giving O(1) precise invalidation. Platform aggregates
are derived from writes happening across every tenant simultaneously, so
there is no single write to hang invalidation off — a short TTL is both simpler
and more honest about what these numbers are: a recent snapshot, not a live
read.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
from collections.abc import Callable

from django.core.cache import cache

logger = logging.getLogger("ledgerflow.platform.cache")

_PREFIX = "platform"


def _key(name: str, args, kwargs) -> str:
    fingerprint = json.dumps(
        {"a": [str(a) for a in args], "k": {k: str(v) for k, v in sorted(kwargs.items())}},
        sort_keys=True,
    )
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
    return f"{_PREFIX}:{name}:{digest}"


def cached_platform(name: str, ttl: int = 120):
    """Cache a platform-wide aggregate for `ttl` seconds.

    Deliberately short. Operators act on these figures — suspending an account,
    chasing a failed payment — and stale data drives wrong actions. Two minutes
    removes the repeated work of several people watching the same dashboard
    without letting anyone act on yesterday's numbers.
    """

    def decorator(fn: Callable):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = _key(name, args, kwargs)
            hit = cache.get(key)
            if hit is not None:
                return hit
            result = fn(*args, **kwargs)
            cache.set(key, result, ttl)
            return result

        wrapper.cache_key = lambda *a, **k: _key(name, a, k)  # type: ignore[attr-defined]
        wrapper.uncached = fn  # type: ignore[attr-defined]
        return wrapper

    return decorator


def invalidate(name: str, *args, **kwargs) -> None:
    """Drop one cached aggregate. Used after an action whose effect an operator
    expects to see immediately (suspending a tenant, granting a comp)."""
    cache.delete(_key(name, args, kwargs))
