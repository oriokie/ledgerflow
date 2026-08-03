"""Base view for platform endpoints.

The counterpart to `apps.common.api_base.TenantScopedAPIView`, and the
important thing about it is what it deliberately does *not* do: it never binds
`app.current_tenant`. Platform endpoints read control-plane tables (tenants,
subscriptions, payments, staff, audit) which carry no RLS policy, and the
absence of a bound tenant means that if one of these views ever touched a
tenant-scoped table by mistake, Postgres' fail-closed policy returns zero rows
rather than someone else's ledger. The isolation guarantee protects the
platform console from itself.

Reaching real customer data is therefore not an accident that can happen — it
requires going through `services.impersonation`, which binds a tenant context
explicitly, against a grant, with an audit row.
"""

from __future__ import annotations

from django.db import transaction

from .permissions import IsPlatformStaff


class PlatformAdminAPIView:
    """Mix into any APIView serving the platform workspace.

    Wraps the request in a transaction so multi-step administrative actions
    (suspend a tenant, cancel its subscription, write the audit row) either all
    land or none do. Without this, a failure between the state change and the
    audit write would leave an unexplained mutation in production — the exact
    thing an audit trail exists to prevent.
    """

    permission_classes = [IsPlatformStaff]
    #: Subclasses set one of these. See `IsPlatformStaff` for resolution order.
    required_capability = None
    capability_map: dict | None = None

    def dispatch(self, request, *args, **kwargs):
        with transaction.atomic():
            return super().dispatch(request, *args, **kwargs)

    @property
    def staff(self):
        return getattr(self.request, "platform_staff", None)
