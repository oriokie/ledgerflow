"""Generic, reusable permission building blocks (not tenancy-specific).
Tenancy's own `IsTenantMember` lives in apps/tenancy/permissions.py since it
encodes a domain rule, not a generic pattern."""

from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission


class ReadOnly(BasePermission):
    """Allow only GET/HEAD/OPTIONS. Compose with `|` for public-read endpoints."""

    def has_permission(self, request, view) -> bool:
        return request.method in SAFE_METHODS


class IsVerifiedUser(BasePermission):
    """Gate write actions behind email verification (e.g. before linking a bank)."""

    message = "Please verify your email address to perform this action."

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated and request.user.is_verified)
