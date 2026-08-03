"""Authorization = membership + role/capability, resolved at the DRF layer.

This permission class does double duty: it both authorizes the request AND
resolves `request.tenant_id`, which `TenantScopedAPIView.initial()` then
binds to the DB session. It must run after authentication (DRF guarantees
this) so `request.user` is populated for JWT requests.

A view declares EITHER `required_role` (simple hierarchy check) OR
`required_capability` (fine-grained RBAC check); if neither is set, any
member (VIEWER+) may proceed.
"""

from __future__ import annotations

import uuid

from rest_framework.permissions import BasePermission

from .models import Role
from .rbac import has_capability, has_role_at_least
from .selectors import membership_for


class IsTenantMember(BasePermission):
    message = "You are not a member of this workspace, or your role is insufficient."

    def has_permission(self, request, view) -> bool:
        request.tenant_id = None
        request.membership = None

        if not request.user or not request.user.is_authenticated:
            return False

        raw_tenant_id = request.headers.get("X-Tenant-ID")
        if not raw_tenant_id:
            self.message = "X-Tenant-ID header is required."
            return False
        try:
            tenant_id = uuid.UUID(raw_tenant_id)
        except ValueError:
            self.message = "X-Tenant-ID must be a valid UUID."
            return False

        membership = membership_for(user=request.user, tenant_id=tenant_id)

        required_capability = getattr(view, "required_capability", None)
        if required_capability is not None:
            authorized = has_capability(membership, required_capability)
        else:
            required_role = getattr(view, "required_role", Role.VIEWER)
            authorized = has_role_at_least(membership, required_role)

        if not authorized:
            return False

        request.tenant_id = tenant_id
        request.membership = membership
        return True
