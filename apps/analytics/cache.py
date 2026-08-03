"""Report caching — a thin adapter over the shared tenant cache.

Deliberately **not** a second caching implementation. `apps.common.cache`
already provides version-stamped, tenant-scoped invalidation and is used by the
intelligence app; a parallel version counter here would mean bumping one leaves
the other serving stale figures, which is exactly the failure a cache must not
have in a financial product.

So this module owns only the report-specific key shape and delegates
invalidation entirely. The single bump point is the ledger's
`post_journal_entry`, which every financial write passes through.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from django.core.cache import cache

from apps.common.cache import current_version, invalidate_tenant
from apps.common.tenant_context import get_current_tenant_id

#: TTL is a backstop only — version bumping is the real invalidation. Short
#: enough that a missed bump (an unreachable cache backend, say) can't leave a
#: figure wrong for long.
DEFAULT_TTL_SECONDS = 300


def invalidate(tenant_id=None) -> None:
    """Orphan every cached report for a tenant.

    Delegates to the shared counter so reports and the intelligence caches
    invalidate together. Exposed here so callers reasoning about reports don't
    need to know where the counter lives.
    """
    invalidate_tenant(tenant_id)


def report_cache_key(*, slug: str, filters_part: str, tenant_id=None) -> str:
    """A key scoped to tenant, version and filters.

    The tenant id appears in the key itself, not just in the version counter.
    Two independent guards on the one thing that must never happen: a coding
    error in the version logic still cannot serve one workspace's figures to
    another.
    """
    tenant_id = str(tenant_id or get_current_tenant_id())
    digest = hashlib.sha256(filters_part.encode()).hexdigest()[:16]
    return f"analytics:report:{tenant_id}:v{current_version(tenant_id)}:{slug}:{digest}"


def cached_report(
    *, slug: str, filters_part: str, compute: Callable[[], Any], ttl: int = DEFAULT_TTL_SECONDS
) -> Any:
    """Return a cached report, computing it on a miss.

    Skips the cache entirely when no tenant is bound: an unscoped read should
    fail closed like every other query in the product rather than quietly
    reading or writing a shared key.
    """
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        return compute()

    key = report_cache_key(slug=slug, filters_part=filters_part, tenant_id=tenant_id)
    hit = cache.get(key)
    if hit is not None:
        return hit

    value = compute()
    cache.set(key, value, ttl)
    return value
