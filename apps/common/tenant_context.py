"""Ambient tenant + actor context.

Multi-tenancy strategy: shared database, row-level scoping by `tenant_id`,
enforced in three layers — this contextvar, the scoped managers, and Postgres
RLS. contextvars (not thread-locals) so isolation survives async views and does
not leak across Celery tasks.

The actor context carries the acting user's id so services can stamp
created_by / updated_by / deleted_by and the audit log without threading the
user through every function signature.
"""

from __future__ import annotations

import contextlib
import uuid
from contextvars import ContextVar

_current_tenant_id: ContextVar[uuid.UUID | None] = ContextVar("current_tenant_id", default=None)
_current_actor_id: ContextVar[uuid.UUID | None] = ContextVar("current_actor_id", default=None)


class UnscopedAccessError(Exception):
    """Raised when tenant-scoped data is queried with no tenant in context."""


def get_current_tenant_id() -> uuid.UUID | None:
    return _current_tenant_id.get()


def require_current_tenant_id() -> uuid.UUID:
    tenant_id = _current_tenant_id.get()
    if tenant_id is None:
        raise UnscopedAccessError(
            "Tenant-scoped access with no active tenant. Wrap in use_tenant(...) "
            "or use the `.unscoped` manager deliberately."
        )
    return tenant_id


def get_current_actor_id() -> uuid.UUID | None:
    return _current_actor_id.get()


#: Scratch space that lives exactly as long as a bound tenant.
#
# For facts that cannot change inside one request but are asked for repeatedly:
# how many members a workspace has, which membership is acting, which accounts
# are visible. The household member-boundary checks consult those on every
# query they guard, so a single transaction listing was asking the same three
# questions five times between them.
#
# Bound to the same ContextVar lifecycle as the tenant itself, which is the
# property that makes it safe: a cache that outlived its tenant would serve one
# household's visibility answers to another, and that is the exact failure the
# whole boundary exists to prevent. It is created on entry and dropped on exit —
# there is no eviction policy to get wrong.
_request_cache: ContextVar[dict | None] = ContextVar("tenant_scoped_cache", default=None)


def cached_per_tenant_scope(key: str, produce):
    """Memoise `produce()` for the life of the current tenant binding.

    Falls straight through to `produce()` when nothing is bound — a management
    command or a test calling a selector directly should behave identically,
    just without the saving.
    """
    cache = _request_cache.get()
    if cache is None:
        return produce()
    if key not in cache:
        cache[key] = produce()
    return cache[key]


def invalidate_tenant_scope_cache(*keys: str) -> None:
    """Drop memoised answers after a write that changes them.

    Narrow on purpose: a writer that changes sharing or membership must say so,
    because the alternative — clearing everything on every write — would make
    the cache useless on exactly the requests that do the most work.
    """
    cache = _request_cache.get()
    if cache is None:
        return
    if not keys:
        cache.clear()
        return
    for key in keys:
        cache.pop(key, None)


@contextlib.contextmanager
def use_tenant(tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None):
    """Bind tenant (and optionally actor) for a request / task / test block."""
    t_token = _current_tenant_id.set(tenant_id)
    a_token = _current_actor_id.set(actor_id) if actor_id is not None else None
    c_token = _request_cache.set({})
    try:
        yield
    finally:
        _current_tenant_id.reset(t_token)
        _request_cache.reset(c_token)
        if a_token is not None:
            _current_actor_id.reset(a_token)


@contextlib.contextmanager
def use_actor(actor_id: uuid.UUID):
    token = _current_actor_id.set(actor_id)
    try:
        yield
    finally:
        _current_actor_id.reset(token)
