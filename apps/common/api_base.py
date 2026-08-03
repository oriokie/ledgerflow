"""Base classes for tenant-scoped API endpoints.

Design note — why this isn't Django middleware:
JWT identity is resolved by DRF's authentication classes inside
`APIView.initial()`, which runs *after* Django's own middleware chain has
already completed for the view. Plain middleware never sees `request.user`
for JWT-authenticated requests, so tenant resolution cannot live there. It has
to happen at the DRF layer, after `perform_authentication` / `check_permissions`.

`TenantScopedAPIView.dispatch()` wraps the request in `transaction.atomic()`
specifically so `SET LOCAL app.current_tenant` (session-local, transaction-
scoped) is guaranteed to unwind when the transaction ends — even on an
exception — rather than relying on cleanup code that could be skipped.
"""

from __future__ import annotations

import uuid

from django.db import transaction

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant


class TenantScopedAPIView:
    """Mix into any APIView/ViewSet whose queryset must be tenant-isolated.
    Requires `IsTenantMember` (or equivalent) in `permission_classes` — that's
    what populates `request.tenant_id`."""

    _tenant_cm = None

    def dispatch(self, request, *args, **kwargs):
        with transaction.atomic():
            return super().dispatch(request, *args, **kwargs)

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)  # runs auth + permissions first
        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            return
        bind_db_tenant(tenant_id)
        actor_id = request.user.id if request.user and request.user.is_authenticated else None
        self._tenant_cm = use_tenant(uuid.UUID(str(tenant_id)), actor_id=actor_id)
        self._tenant_cm.__enter__()

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if self._tenant_cm is not None:
            self._tenant_cm.__exit__(None, None, None)
            self._tenant_cm = None
        return response


class WriteRequiresMemberMixin:
    """Method-aware authorization: safe methods (GET/HEAD/OPTIONS) need only
    VIEWER; anything that mutates needs MEMBER. `required_role` is read by the
    permission during `initial()`, so it must be a property evaluated then —
    setting it inside the view method would run after the check.

    Read the role from the request method rather than declaring two view
    classes per resource, keeping a single cohesive view per resource.
    """

    _SAFE = frozenset({"GET", "HEAD", "OPTIONS"})

    @property
    def required_role(self):
        from apps.tenancy.models import Role

        return Role.VIEWER if self.request.method in self._SAFE else Role.MEMBER
