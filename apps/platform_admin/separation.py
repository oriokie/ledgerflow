"""Separation between platform operators and customer workspaces.

An operator account is a privileged instrument for acting on *other people's*
accounts. Letting the same login also own a household workspace is a bad idea
for three separate reasons, any one of which is sufficient:

* **Audit clarity.** The impersonation trail answers "when did staff touch
  customer data". If the operator also has their own workspace, ordinary
  personal activity and administrative activity are interleaved under one
  identity, and reconstructing what happened after an incident becomes an
  exercise in guessing.
* **Blast radius.** A compromised operator credential already exposes the
  control plane. It should not additionally expose someone's personal finances,
  and personal finances should not be one credential away from the admin
  console.
* **Entitlement confusion.** Plan limits, billing and dunning all assume a
  workspace has a paying owner. An operator's workspace is neither paying nor
  churnable, and it quietly pollutes every metric the console reports.

This is policy, not a law of nature, so it is a setting. The default is
separation; deployments where one person is genuinely both the operator and a
customer — a solo founder dogfooding — can turn it off knowingly rather than
discovering the restriction and working around it.

Enforcement is at the service layer, so it holds for the API, a management
command and a Celery task alike. The frontend also routes staff to the console,
but that is convenience; this is the control.
"""

from __future__ import annotations

from django.conf import settings


class PlatformSeparationError(Exception):
    """Raised when an operator account tries to act as a customer."""


def separation_enforced() -> bool:
    """Whether platform staff are barred from owning customer workspaces."""
    return bool(getattr(settings, "PLATFORM_STAFF_SEPARATE_FROM_TENANTS", True))


def is_platform_staff(user) -> bool:
    """True when this user holds *active* platform authority.

    Deliberately checks `is_active`: revoking someone's platform access should
    also return their ability to be an ordinary customer, rather than leaving
    them locked out of both halves of the product.
    """
    if user is None or not getattr(user, "pk", None):
        return False
    from apps.platform_admin.models import PlatformStaff

    return PlatformStaff.objects.filter(user=user, is_active=True).exists()


def assert_may_join_workspace(user, *, action: str = "join a workspace") -> None:
    """Guard the customer-side entry points.

    Called by workspace creation and invitation acceptance — the two ways an
    account becomes a member of a tenant.
    """
    if not separation_enforced():
        return
    if is_platform_staff(user):
        raise PlatformSeparationError(
            f"This is a platform administration account, so it cannot {action}. "
            "Platform staff work in the admin console; use a separate personal "
            "account for your own finances."
        )


def existing_memberships(user) -> int:
    """How many customer workspaces this user already belongs to.

    Used when appointing staff: pre-existing memberships are reported rather
    than silently severed. Removing someone from their own household because
    they were given a support role would be a startling side effect of a
    permissions change, and their data is not ours to delete.
    """
    if user is None or not getattr(user, "pk", None):
        return 0
    from apps.tenancy.models import Membership

    return Membership.objects.filter(user=user).count()
