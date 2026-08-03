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


@contextlib.contextmanager
def use_tenant(tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None):
    """Bind tenant (and optionally actor) for a request / task / test block."""
    t_token = _current_tenant_id.set(tenant_id)
    a_token = _current_actor_id.set(actor_id) if actor_id is not None else None
    try:
        yield
    finally:
        _current_tenant_id.reset(t_token)
        if a_token is not None:
            _current_actor_id.reset(a_token)


@contextlib.contextmanager
def use_actor(actor_id: uuid.UUID):
    token = _current_actor_id.set(actor_id)
    try:
        yield
    finally:
        _current_actor_id.reset(token)
