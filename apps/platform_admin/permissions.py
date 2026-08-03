"""Authorization for the platform workspace.

Mirrors the shape of `apps.tenancy.permissions.IsTenantMember` — one permission
class that both authorizes the request and attaches the resolved actor to it —
but resolves an entirely different subject. There is no `X-Tenant-ID` here and
no membership: the question is "is this user platform staff, and may they do
the thing this view declares".

A view declares its requirement as `required_capability`. Omitting it is not a
way to get a public endpoint; it means "any active staff member", which is
still a closed set. Endpoints that genuinely need finer logic (e.g. refund
approval needing a *different* capability than refund creation) declare it
per-method via `capability_map`.
"""

from __future__ import annotations

import ipaddress

from rest_framework.permissions import BasePermission

from .models import PlatformStaff
from .rbac import PlatformCapability


def client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def ip_allowed(ip: str | None, allowlist) -> bool:
    """An empty allowlist means unrestricted; a non-empty one is fail-closed.

    Entries may be plain addresses or CIDR blocks. A malformed entry is treated
    as non-matching rather than as an error: a typo in one office range must not
    silently widen access, and must not lock everyone out either — the other
    entries still apply.
    """
    if not allowlist:
        return True
    if not ip:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            if address in ipaddress.ip_network(str(entry), strict=False):
                return True
        except ValueError:
            continue
    return False


class IsPlatformStaff(BasePermission):
    """Gate every platform endpoint. Resolves `request.platform_staff`."""

    message = "Platform administration access is required."

    def has_permission(self, request, view) -> bool:
        request.platform_staff = None

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        staff = PlatformStaff.objects.filter(user=user, is_active=True).select_related("user").first()
        if staff is None:
            # Deliberately the same message as an insufficient capability: a
            # probe should not be able to distinguish "you are not staff" from
            # "you are staff but may not do this", which would confirm the
            # existence of an administrative account.
            return False

        if not ip_allowed(client_ip(request), staff.allowed_ips):
            self.message = "Platform access is not permitted from this network."
            return False

        if staff.require_mfa and not self._has_mfa(user):
            # Login already forces a second factor for anyone enrolled, so
            # requiring enrolment is what makes "this session was MFA'd" true.
            # Checking enrolment here (rather than a token claim) also means an
            # operator who removes their authenticator loses platform access on
            # the next request, not at the next login.
            self.message = "Enable two-factor authentication to use the platform workspace."
            return False

        required = self._required_capability(request, view)
        if required is not None and not staff.has(required):
            return False

        request.platform_staff = staff
        return True

    @staticmethod
    def _has_mfa(user) -> bool:
        from apps.users.services.mfa import user_has_mfa_enabled

        return user_has_mfa_enabled(user)

    @staticmethod
    def _required_capability(request, view) -> PlatformCapability | None:
        capability_map = getattr(view, "capability_map", None)
        if capability_map:
            mapped = capability_map.get(request.method)
            if mapped is not None:
                return mapped
        return getattr(view, "required_capability", None)
