"""Binds the Postgres RLS session GUC (`app.current_tenant`).

Used by both the API layer (`apps.common.api_base.TenantScopedAPIView`) and
anything else that writes tenant-scoped rows outside of a request — service
unit tests, management commands, data backfills. Must be called inside an
already-open transaction: `SET LOCAL` is transaction-scoped, which is what
guarantees it unwinds even if the caller raises.
"""

from __future__ import annotations

from django.db import connection, transaction


def bind_db_tenant(tenant_id) -> None:
    if connection.vendor != "postgresql":
        return  # sqlite (rare local/CI fallback) has no RLS; contextvar scoping still applies
    # SET LOCAL outside a transaction is a silent no-op — RLS would then fall
    # back to the fail-closed policy (zero rows), but a caller that THINKS it
    # bound a tenant and silently sees nothing is a nasty bug. Refuse loudly so
    # the mistake surfaces in development, never in production behavior.
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError(
            "bind_db_tenant() must run inside a transaction; SET LOCAL is "
            "transaction-scoped. Wrap the call in transaction.atomic() "
            "(the API layer and tenant_scope() already do)."
        )
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.current_tenant = %s", [str(tenant_id)])
