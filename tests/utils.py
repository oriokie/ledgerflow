"""Test-only tenant scoping helper.

Mirrors exactly what `apps.common.api_base.TenantScopedAPIView` does for a real
request, so service/selector unit tests exercise real RLS enforcement instead
of only the Python-level contextvar check. Any test that creates or reads
RLS-protected rows directly (bypassing the HTTP layer) should use this rather
than the bare `use_tenant` contextmanager.
"""

from __future__ import annotations

import contextlib
import uuid

from django.db import transaction

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant


@contextlib.contextmanager
def tenant_scope(tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None):
    with transaction.atomic():
        bind_db_tenant(tenant_id)
        with use_tenant(tenant_id, actor_id=actor_id):
            yield
