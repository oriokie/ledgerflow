"""Tenant lifecycle and subscription operations performed by platform staff.

Every mutating function takes an explicit `reason` and writes an audit row.
That is not ceremony: these are actions taken *on* a customer without the
customer present, and the only thing that makes them accountable afterwards is
the record of who did it and why.

Where an operation already exists as a tenant-facing service it is delegated
to rather than reimplemented — `apps.billing.services.subscribe` handles plan
changes here exactly as it does when an owner clicks upgrade. Reimplementing
would let the two paths drift, and the customer-facing one is the one with the
tests.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.billing import invoicing
from apps.billing import services as billing
from apps.billing.models import Plan, Subscription, SubscriptionStatus
from apps.tenancy.models import Tenant

from ..audit import diff, record
from ..models import PlatformStaff

logger = logging.getLogger("ledgerflow.platform.tenants")

MODULE = "tenants"


class TenantAdminError(Exception):
    """Raised for administrative operations invalid in the current state."""


def _require_reason(reason: str, action: str) -> str:
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise TenantAdminError(f"{action} needs a reason — it will be recorded against this account.")
    return reason


# ------------------------------------------------------------------ lifecycle
@transaction.atomic
def suspend(
    *, tenant: Tenant, actor: PlatformStaff, reason: str, request=None
) -> Tenant:
    """Revoke workspace access without touching any data.

    Suspension is deliberately reversible and lossless. The subscription is
    left alone: a workspace suspended for abuse should keep billing, and one
    suspended for non-payment is already handled by the dunning engine, which
    owns that state transition.
    """
    reason = _require_reason(reason, "Suspending a workspace")
    if not tenant.is_active:
        return tenant

    tenant.is_active = False
    tenant.save(update_fields=["is_active", "updated_at"])

    record(
        action="tenant.suspended",
        staff=actor,
        module=MODULE,
        target_type="tenancy.Tenant",
        target_id=tenant.id,
        tenant_id=tenant.id,
        changes={"is_active": [True, False]},
        reason=reason,
        request=request,
    )
    return tenant


@transaction.atomic
def reactivate(*, tenant: Tenant, actor: PlatformStaff, reason: str, request=None) -> Tenant:
    reason = _require_reason(reason, "Reactivating a workspace")
    if tenant.is_active:
        return tenant

    tenant.is_active = True
    tenant.save(update_fields=["is_active", "updated_at"])

    record(
        action="tenant.reactivated",
        staff=actor,
        module=MODULE,
        target_type="tenancy.Tenant",
        target_id=tenant.id,
        tenant_id=tenant.id,
        changes={"is_active": [False, True]},
        reason=reason,
        request=request,
    )
    return tenant


@transaction.atomic
def update_tenant(
    *,
    tenant: Tenant,
    actor: PlatformStaff,
    reason: str = "",
    request=None,
    **fields,
) -> Tenant:
    """Edit workspace metadata. Only a fixed set of fields is writable.

    An allowlist rather than `setattr` over whatever arrives: `is_active` has
    its own audited operation and must not be flippable through a generic edit,
    which would produce a suspension with no suspension audit row.
    """
    editable = {"name", "billing_email", "country", "default_timezone", "default_locale", "type"}
    unknown = set(fields) - editable
    if unknown:
        raise TenantAdminError(f"These fields can't be edited here: {', '.join(sorted(unknown))}.")

    before = {f: getattr(tenant, f) for f in editable}
    changed = []
    for field, value in fields.items():
        if value is None:
            continue
        if field == "country":
            value = str(value).upper()[:2]
        setattr(tenant, field, value)
        changed.append(field)

    if not changed:
        return tenant
    tenant.save(update_fields=[*changed, "updated_at"])

    after = {f: getattr(tenant, f) for f in editable}
    record(
        action="tenant.updated",
        staff=actor,
        module=MODULE,
        target_type="tenancy.Tenant",
        target_id=tenant.id,
        tenant_id=tenant.id,
        changes=diff(before, after),
        reason=reason,
        request=request,
    )
    return tenant


@transaction.atomic
def close_tenant(*, tenant: Tenant, actor: PlatformStaff, reason: str, request=None) -> Tenant:
    """Close a workspace on the customer's behalf.

    Reuses the tenancy service's soft-close semantics — deactivate now, emit an
    event a purge worker consumes after the grace period — rather than deleting
    rows here. Irreversible erasure stays a deliberate asynchronous step, which
    is what makes an accidental click recoverable.
    """
    from apps.common.outbox import OutboxEvent

    reason = _require_reason(reason, "Closing a workspace")

    tenant.is_active = False
    tenant.save(update_fields=["is_active", "updated_at"])
    OutboxEvent.objects.create(
        tenant_id=tenant.id,
        aggregate_type="tenancy.Tenant",
        aggregate_id=tenant.id,
        event_type="tenancy.workspace.closed",
        payload={"closed_by_platform_staff": str(actor.user_id), "reason": reason},
    )

    record(
        action="tenant.closed",
        staff=actor,
        module=MODULE,
        target_type="tenancy.Tenant",
        target_id=tenant.id,
        tenant_id=tenant.id,
        changes={"is_active": [True, False]},
        reason=reason,
        request=request,
    )
    return tenant


# --------------------------------------------------------------- subscriptions
@transaction.atomic
def change_plan(
    *,
    tenant: Tenant,
    plan: Plan,
    actor: PlatformStaff,
    reason: str,
    request=None,
) -> Subscription:
    """Move a workspace to another plan.

    Delegates to the customer-facing `billing.subscribe`, so an operator-driven
    upgrade goes through exactly the same code as a self-serve one.
    """
    reason = _require_reason(reason, "Changing a plan")
    current = billing.get_subscription(tenant_id=tenant.id)
    before = current.plan.name if current else None

    method = None
    if plan.price_minor > 0:
        from apps.billing.models import PaymentMethod

        method = (
            PaymentMethod.objects.filter(tenant_id=tenant.id, is_default=True).first()
            or PaymentMethod.objects.filter(tenant_id=tenant.id).order_by("-created_at").first()
        )
        if method is None:
            raise TenantAdminError(
                "This workspace has no payment method; issue a complimentary subscription instead."
            )

    try:
        sub = billing.subscribe(tenant_id=tenant.id, plan=plan, payment_method=method)
    except billing.BillingError as exc:
        raise TenantAdminError(str(exc)) from exc

    record(
        action="subscription.plan_changed",
        staff=actor,
        module="billing",
        target_type="billing.Subscription",
        target_id=sub.id,
        tenant_id=tenant.id,
        changes={"plan": [before, plan.name]},
        reason=reason,
        request=request,
    )
    return sub


@transaction.atomic
def grant_complimentary(
    *,
    tenant: Tenant,
    plan: Plan,
    actor: PlatformStaff,
    reason: str,
    months: int = 1,
    request=None,
) -> Subscription:
    """Give a workspace a paid plan at no charge.

    Distinct from `change_plan` because it takes no payment method and creates
    no charge — the subscription is activated directly and marked in metadata
    so it is recognisable in revenue reporting. A comp counted as revenue would
    quietly inflate MRR, so `metrics` excludes it.
    """
    reason = _require_reason(reason, "Granting a complimentary subscription")
    if months < 1:
        raise TenantAdminError("A complimentary subscription must run for at least a month.")

    now = timezone.now()
    sub = Subscription.objects.filter(tenant_id=tenant.id).select_related("plan").first()
    before = sub.plan.name if sub else None
    if sub is None:
        sub = Subscription(tenant_id=tenant.id, plan=plan)

    sub.plan = plan
    sub.status = SubscriptionStatus.ACTIVE
    sub.current_period_start = now
    sub.current_period_end = now + timedelta(days=30 * months)
    sub.cancel_at_period_end = False
    sub.canceled_at = None
    sub.provider = ""
    sub.provider_ref = ""
    sub.metadata = {
        **(sub.metadata or {}),
        "complimentary": True,
        "complimentary_until": sub.current_period_end.isoformat(),
        "granted_by": str(actor.user_id),
        "reason": reason,
    }
    sub.save()

    record(
        action="subscription.comped",
        staff=actor,
        module="billing",
        target_type="billing.Subscription",
        target_id=sub.id,
        tenant_id=tenant.id,
        changes={"plan": [before, plan.name], "months": [None, months]},
        reason=reason,
        request=request,
    )
    return sub


@transaction.atomic
def extend_trial(
    *, tenant: Tenant, actor: PlatformStaff, days: int, reason: str, request=None
) -> Subscription:
    """Push a trial's end date out.

    Extends from whichever is later — the current trial end or now — so
    extending an already-lapsed trial by 7 days gives a real week, not a date
    still in the past.
    """
    reason = _require_reason(reason, "Extending a trial")
    if days < 1:
        raise TenantAdminError("A trial extension must be at least one day.")

    sub = Subscription.objects.filter(tenant_id=tenant.id).select_related("plan").first()
    if sub is None:
        raise TenantAdminError("This workspace has no subscription to extend.")

    now = timezone.now()
    base = max(sub.trial_end or now, now)
    before = sub.trial_end

    sub.trial_end = base + timedelta(days=days)
    sub.status = SubscriptionStatus.TRIALING
    sub.current_period_end = sub.trial_end
    sub.save(update_fields=["trial_end", "status", "current_period_end", "updated_at"])

    record(
        action="subscription.trial_extended",
        staff=actor,
        module="billing",
        target_type="billing.Subscription",
        target_id=sub.id,
        tenant_id=tenant.id,
        changes={"trial_end": [before.isoformat() if before else None, sub.trial_end.isoformat()]},
        reason=reason,
        context={"days": days},
        request=request,
    )
    return sub


@transaction.atomic
def cancel_subscription(
    *, tenant: Tenant, actor: PlatformStaff, reason: str, immediate: bool = False, request=None
) -> Subscription:
    reason = _require_reason(reason, "Cancelling a subscription")
    try:
        sub = billing.cancel_subscription(tenant_id=tenant.id, at_period_end=not immediate)
    except billing.BillingError as exc:
        raise TenantAdminError(str(exc)) from exc

    record(
        action="subscription.cancelled",
        staff=actor,
        module="billing",
        target_type="billing.Subscription",
        target_id=sub.id,
        tenant_id=tenant.id,
        changes={"immediate": [None, immediate]},
        reason=reason,
        request=request,
    )
    return sub


@transaction.atomic
def resume_subscription(
    *, tenant: Tenant, actor: PlatformStaff, reason: str, request=None
) -> Subscription:
    """Undo a pending cancellation."""
    reason = _require_reason(reason, "Resuming a subscription")
    sub = Subscription.objects.filter(tenant_id=tenant.id).select_related("plan").first()
    if sub is None:
        raise TenantAdminError("This workspace has no subscription.")
    if not sub.cancel_at_period_end and sub.status != SubscriptionStatus.CANCELED:
        raise TenantAdminError("This subscription isn't scheduled to cancel.")

    sub.cancel_at_period_end = False
    sub.canceled_at = None
    if sub.status == SubscriptionStatus.CANCELED:
        sub.status = SubscriptionStatus.ACTIVE
    sub.save(update_fields=["cancel_at_period_end", "canceled_at", "status", "updated_at"])

    record(
        action="subscription.resumed",
        staff=actor,
        module="billing",
        target_type="billing.Subscription",
        target_id=sub.id,
        tenant_id=tenant.id,
        reason=reason,
        request=request,
    )
    return sub


# --------------------------------------------------------------------- credits
@transaction.atomic
def apply_credit(
    *,
    tenant: Tenant,
    actor: PlatformStaff,
    amount_minor: int,
    currency: str,
    reason: str,
    kind: str = "goodwill",
    request=None,
):
    """Issue account credit against a workspace."""
    reason = _require_reason(reason, "Issuing credit")
    credit = invoicing.issue_credit(
        tenant_id=tenant.id,
        amount_minor=amount_minor,
        currency=currency,
        kind=kind,
        reason=reason,
        issued_by=actor.user,
    )
    record(
        action="credit.issued",
        staff=actor,
        module="billing",
        target_type="billing.Credit",
        target_id=credit.id,
        tenant_id=tenant.id,
        changes={"amount_minor": [None, amount_minor], "currency": [None, currency]},
        reason=reason,
        request=request,
    )
    return credit


@transaction.atomic
def reset_billing_state(
    *, tenant: Tenant, actor: PlatformStaff, reason: str, request=None
) -> Subscription | None:
    """Clear a wedged billing state: close dunning, restore access, reactivate.

    The support escape hatch for accounts stuck by a provider outage or a bug —
    charged but still past-due, suspended after paying. It changes state, never
    money: no refund, no charge, no plan change. Anything involving money has
    its own audited operation with its own capability.
    """
    from apps.billing.dunning import close_case
    from apps.billing.dunning_models import LIVE_CASE_STATUSES, DunningCase, DunningCaseStatus

    reason = _require_reason(reason, "Resetting billing state")

    cases = list(DunningCase.objects.filter(tenant_id=tenant.id, status__in=LIVE_CASE_STATUSES))
    for case in cases:
        close_case(case=case, status=DunningCaseStatus.CANCELLED, note=f"Reset by staff: {reason}")

    sub = Subscription.objects.filter(tenant_id=tenant.id).select_related("plan").first()
    before_status = sub.status if sub else None
    if sub is not None and sub.status == SubscriptionStatus.PAST_DUE:
        sub.status = SubscriptionStatus.ACTIVE
        sub.save(update_fields=["status", "updated_at"])

    was_active = tenant.is_active
    if not tenant.is_active:
        tenant.is_active = True
        tenant.save(update_fields=["is_active", "updated_at"])

    record(
        action="billing.state_reset",
        staff=actor,
        module="billing",
        target_type="tenancy.Tenant",
        target_id=tenant.id,
        tenant_id=tenant.id,
        changes={
            "subscription_status": [before_status, sub.status if sub else None],
            "is_active": [was_active, True],
        },
        reason=reason,
        context={"dunning_cases_closed": len(cases)},
        request=request,
    )
    return sub
