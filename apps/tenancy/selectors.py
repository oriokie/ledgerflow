"""Tenancy read side. Selectors return optimized querysets and never mutate."""

from __future__ import annotations

from .models import Membership, Tenant


def workspaces_for_user(user) -> list[Tenant]:
    memberships = Membership.objects.filter(user=user).select_related("tenant").order_by("tenant__name")
    return [m.tenant for m in memberships]


def memberships_for_user(user):
    """Memberships + tenant in one query — what the workspace-switcher UI needs.
    Closed (inactive) workspaces are filtered out so they disappear on closure."""
    return (
        Membership.objects.filter(user=user, tenant__is_active=True)
        .select_related("tenant")
        .order_by("tenant__name")
    )


def membership_for(*, user, tenant_id) -> Membership | None:
    return Membership.objects.filter(user=user, tenant_id=tenant_id).first()


def members_of(tenant) -> list[Membership]:
    return list(Membership.objects.filter(tenant=tenant).select_related("user").order_by("created_at"))
