"""
Billing service layer.

All subscription/payment business logic lives here; views stay thin. The
service binds tenant context explicitly where needed (webhooks arrive with no
request tenant) and talks to providers only through the PaymentProvider
interface.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    BillingInterval,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Plan,
    Subscription,
    SubscriptionStatus,
    WebhookEvent,
)
from .providers import get_provider
from .providers.base import PaymentError


class BillingError(Exception): ...


# --------------------------------------------------------------------------- plans
def list_plans(*, currency: str = "USD") -> list[Plan]:
    return list(Plan.objects.filter(is_active=True, currency=currency).order_by("sort_order", "price_minor"))


logger = logging.getLogger("ledgerflow.billing")


def _free_plan(currency: str) -> Plan | None:
    return (
        Plan.objects.filter(is_active=True, price_minor=0, currency=currency).order_by("sort_order").first()
    )


# --------------------------------------------------------------------------- subscription reads
def get_subscription(*, tenant_id) -> Subscription | None:
    return Subscription.objects.filter(tenant_id=tenant_id).select_related("plan").first()


def _period_end(interval: str, start) -> timezone.datetime:
    return start + (timedelta(days=365) if interval == BillingInterval.YEARLY else timedelta(days=30))


def start_trial(*, tenant_id) -> Subscription | None:
    """Put a brand-new workspace on the Basic trial — card-free, TRIAL_DAYS long.

    Card-free by design: a trial that demands payment details first measures
    willingness to cancel, not willingness to pay. The clock, not a stored
    card, is what converts — entitlements stop granting the moment trial_end
    passes (see entitlements.resolve_entitlements), so nothing here needs a
    scheduled job to be correct.

    Returns None rather than raising when no Basic plan exists: a deployment
    that has not seeded its catalogue gets the legacy unmetered behaviour, not
    a workspace that cannot be created.
    """
    from .plan_catalogue import TRIAL_DAYS

    if Subscription.objects.filter(tenant_id=tenant_id).exists():
        return None  # never restart a trial on re-entry

    plan = (
        Plan.objects.filter(is_active=True, tier="basic", interval=BillingInterval.MONTHLY)
        .order_by("sort_order")
        .first()
    )
    if plan is None:
        logger.warning("No active Basic plan; workspace %s starts unmetered.", tenant_id)
        return None

    now = timezone.now()
    return Subscription.objects.create(
        tenant_id=tenant_id,
        plan=plan,
        status=SubscriptionStatus.TRIALING,
        trial_end=now + timedelta(days=TRIAL_DAYS),
        current_period_start=now,
        current_period_end=now + timedelta(days=TRIAL_DAYS),
    )


# --------------------------------------------------------------------------- subscribe / change
@transaction.atomic
def subscribe(*, tenant_id, plan: Plan, payment_method: PaymentMethod | None = None) -> Subscription:
    """Create or move a tenant onto `plan`.

    Free plans activate immediately with no charge. Paid plans require a payment
    method and attempt an initial charge; if the provider needs async
    confirmation (M-PESA STK, 3-D Secure) the subscription is left INCOMPLETE
    until the webhook confirms.
    """
    now = timezone.now()
    sub = Subscription.objects.filter(tenant_id=tenant_id).select_related("plan").first()

    # Free plan: no provider, active immediately.
    if plan.price_minor == 0:
        if sub is None:
            sub = Subscription(tenant_id=tenant_id, plan=plan)
        sub.plan = plan
        sub.status = SubscriptionStatus.ACTIVE
        sub.current_period_start = now
        sub.current_period_end = _period_end(plan.interval, now)
        sub.cancel_at_period_end = False
        sub.canceled_at = None
        sub.provider = ""
        sub.provider_ref = ""
        sub.save()
        return sub

    if payment_method is None:
        raise BillingError("A payment method is required for paid plans.")

    if sub is None:
        sub = Subscription(tenant_id=tenant_id, plan=plan)
    sub.plan = plan
    sub.provider = payment_method.provider
    sub.status = SubscriptionStatus.INCOMPLETE
    sub.save()

    result = _charge_for_subscription(sub=sub, plan=plan, payment_method=payment_method)

    if result.status == PaymentStatus.SUCCEEDED:
        sub.status = SubscriptionStatus.ACTIVE
        sub.current_period_start = now
        sub.current_period_end = _period_end(plan.interval, now)
        sub.provider_ref = result.provider_ref
        sub.save()
    elif result.status == PaymentStatus.PENDING:
        # Async confirmation pending — stays INCOMPLETE; webhook will activate.
        sub.provider_ref = result.provider_ref
        sub.save()
    else:
        raise BillingError(f"Initial payment failed: {result.failure_reason or 'declined'}")
    return sub


@transaction.atomic
def cancel_subscription(*, tenant_id, at_period_end: bool = True) -> Subscription:
    sub = Subscription.objects.filter(tenant_id=tenant_id).select_related("plan").first()
    if sub is None:
        raise BillingError("No subscription to cancel.")
    if at_period_end:
        sub.cancel_at_period_end = True
    else:
        sub.status = SubscriptionStatus.CANCELED
        sub.canceled_at = timezone.now()
    sub.save()
    return sub


# --------------------------------------------------------------------------- payment methods
@transaction.atomic
def add_payment_method(
    *, tenant_id, provider_key: str, token: str, kind: str, make_default: bool = True
) -> PaymentMethod:
    """Exchange a client-side token for a stored payment method. Raw card data
    never reaches us — the provider tokenizes it client-side."""
    provider = get_provider(provider_key)
    try:
        result = provider.attach_payment_method(tenant_id=str(tenant_id), token=token, kind=kind)
    except PaymentError as exc:
        raise BillingError(str(exc)) from exc

    if make_default:
        PaymentMethod.objects.filter(tenant_id=tenant_id, is_default=True).update(is_default=False)

    return PaymentMethod.objects.create(
        tenant_id=tenant_id,
        kind=result.kind,
        is_default=make_default,
        brand=result.brand,
        last4=result.last4,
        exp_month=result.exp_month,
        exp_year=result.exp_year,
        phone_masked=result.phone_masked,
        provider=provider_key,
        provider_ref=result.provider_ref,
        metadata=result.metadata,
    )


def list_payment_methods(*, tenant_id) -> list[PaymentMethod]:
    return list(PaymentMethod.objects.filter(tenant_id=tenant_id).order_by("-is_default", "-created_at"))


@transaction.atomic
def set_default_payment_method(*, tenant_id, payment_method_id) -> PaymentMethod:
    """Promote a saved method to the one renewals charge.

    Previously a method could only become the default at the moment it was
    added, which left no way to switch back to an existing card — the only
    route was to delete and re-add it, and re-adding needs a fresh client-side
    token the user may not be in a position to produce.

    Demote-then-promote runs inside one transaction so the workspace is never
    observably left with two defaults or none.
    """
    method = PaymentMethod.objects.filter(tenant_id=tenant_id, id=payment_method_id).first()
    if method is None:
        raise BillingError("That payment method doesn't exist.")
    if method.is_default:
        return method

    PaymentMethod.objects.filter(tenant_id=tenant_id, is_default=True).update(is_default=False)
    method.is_default = True
    method.save(update_fields=["is_default"])
    return method


@transaction.atomic
def remove_payment_method(*, tenant_id, payment_method_id) -> None:
    """Delete a saved method, promoting a successor if it was the default.

    Removing the default used to leave a workspace holding several methods and
    no default at all. Renewal falls back to the newest method in that state,
    so nothing broke outright — but which card gets charged would have changed
    silently, without the user choosing it. Promoting explicitly keeps the
    stored intent honest and the UI's "Default" badge meaningful.
    """
    method = PaymentMethod.objects.filter(tenant_id=tenant_id, id=payment_method_id).first()
    if method is None:
        return
    was_default = method.is_default
    method.delete()

    if was_default:
        successor = PaymentMethod.objects.filter(tenant_id=tenant_id).order_by("-created_at").first()
        if successor is not None:
            successor.is_default = True
            successor.save(update_fields=["is_default"])


# --------------------------------------------------------------------------- charges
def _charge_for_subscription(*, sub: Subscription, plan: Plan, payment_method: PaymentMethod):
    provider = get_provider(payment_method.provider)
    payment = Payment.objects.create(
        tenant_id=sub.tenant_id,
        subscription=sub,
        amount_minor=plan.price_minor,
        currency=plan.currency,
        status=PaymentStatus.PENDING,
        provider=payment_method.provider,
        description=f"{plan.name} subscription",
    )
    try:
        result = provider.charge(
            tenant_id=str(sub.tenant_id),
            amount_minor=plan.price_minor,
            currency=plan.currency,
            payment_method_ref=payment_method.provider_ref,
            description=f"{plan.name} subscription",
            idempotency_key=f"sub-{sub.id}-{uuid.uuid4().hex[:8]}",
        )
    except PaymentError as exc:
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = str(exc)
        payment.save(update_fields=["status", "failure_reason", "updated_at"])
        raise BillingError(str(exc)) from exc

    payment.provider_ref = result.provider_ref
    if result.success:
        payment.status = PaymentStatus.SUCCEEDED
    elif result.requires_action:
        payment.status = PaymentStatus.PENDING
    else:
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = result.failure_reason
    payment.save(update_fields=["provider_ref", "status", "failure_reason", "updated_at"])
    return payment


def list_payments(*, tenant_id) -> list[Payment]:
    return list(Payment.objects.filter(tenant_id=tenant_id).order_by("-created_at")[:100])


@transaction.atomic
def retry_payment(*, tenant_id) -> Subscription:
    """Recover a subscription stuck in past_due/incomplete by re-charging the
    default payment method. On success the subscription reactivates for a fresh
    period; on failure it stays past_due and a BillingError explains why."""
    sub = Subscription.objects.select_for_update().select_related("plan").filter(tenant_id=tenant_id).first()
    if sub is None:
        raise BillingError("There's no subscription to retry.")
    if sub.status not in (SubscriptionStatus.PAST_DUE, SubscriptionStatus.INCOMPLETE):
        raise BillingError("This subscription doesn't need a payment retry.")
    if sub.plan.price_minor == 0:
        # Nothing to charge — just activate.
        _activate_period(sub)
        return sub

    method = (
        PaymentMethod.objects.filter(tenant_id=tenant_id, is_default=True).first()
        or PaymentMethod.objects.filter(tenant_id=tenant_id).order_by("-created_at").first()
    )
    if method is None:
        raise BillingError("Add a payment method before retrying.")

    payment = _charge_for_subscription(sub=sub, plan=sub.plan, payment_method=method)
    if payment.status == PaymentStatus.SUCCEEDED:
        _activate_period(sub)
    elif payment.status == PaymentStatus.PENDING:
        pass  # provider needs async confirmation; webhook will finalize
    else:
        sub.status = SubscriptionStatus.PAST_DUE
        sub.save(update_fields=["status", "updated_at"])
        raise BillingError(payment.failure_reason or "The payment was declined.")
    return sub


def _activate_period(sub: Subscription) -> None:
    now = timezone.now()
    sub.status = SubscriptionStatus.ACTIVE
    sub.current_period_start = now
    sub.current_period_end = _period_end(sub.plan.interval, now)
    sub.save(update_fields=["status", "current_period_start", "current_period_end", "updated_at"])


# --------------------------------------------------------------------------- webhooks
@transaction.atomic
def handle_webhook(*, provider_key: str, body: bytes, headers: dict[str, str]) -> str:
    """Verify, de-duplicate, and apply an inbound provider webhook. Returns a
    short status string. Idempotent: a re-delivered event is a no-op."""
    provider = get_provider(provider_key)
    try:
        result = provider.parse_webhook(body=body, headers=headers)
    except PaymentError as exc:
        raise BillingError(str(exc)) from exc

    event, created = WebhookEvent.objects.get_or_create(
        provider=provider_key,
        event_id=result.event_id,
        defaults={"event_type": result.event_type, "payload": result.raw},
    )
    if not created and event.processed_at is not None:
        return "duplicate"  # already applied — at-least-once delivery guard

    try:
        _apply_webhook(result)
        event.processed_at = timezone.now()
        event.save(update_fields=["processed_at"])
        return "processed"
    except Exception as exc:  # keep the event row for retry/debugging
        event.error = str(exc)
        event.save(update_fields=["error"])
        raise


def _apply_webhook(result) -> None:
    if result.normalized_type == "payment.succeeded":
        payment = Payment.objects.filter(provider_ref=result.provider_ref).first()
        if payment:
            payment.status = PaymentStatus.SUCCEEDED
            payment.save(update_fields=["status", "updated_at"])
            sub = payment.subscription
            if sub and sub.status == SubscriptionStatus.INCOMPLETE:
                now = timezone.now()
                sub.status = SubscriptionStatus.ACTIVE
                sub.current_period_start = now
                sub.current_period_end = _period_end(sub.plan.interval, now)
                sub.save(update_fields=["status", "current_period_start", "current_period_end", "updated_at"])
    elif result.normalized_type == "payment.failed":
        payment = Payment.objects.filter(provider_ref=result.provider_ref).first()
        if payment:
            payment.status = PaymentStatus.FAILED
            payment.save(update_fields=["status", "updated_at"])
            # Reflect the failure on the subscription so the owner is prompted to recover.
            sub = payment.subscription
            if sub and sub.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.INCOMPLETE):
                sub.status = SubscriptionStatus.PAST_DUE
                sub.save(update_fields=["status", "updated_at"])
    elif result.normalized_type == "subscription.canceled":
        sub = Subscription.objects.filter(provider_ref=result.provider_ref).first()
        if sub:
            sub.status = SubscriptionStatus.CANCELED
            sub.canceled_at = timezone.now()
            sub.save(update_fields=["status", "canceled_at", "updated_at"])
