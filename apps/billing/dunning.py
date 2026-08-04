"""Dunning engine — scheduled recovery of failed payments.

The engine writes a full schedule up front (`open_case` creates every retry,
reminder, suspension and abandonment attempt at once) and then executes due
attempts one at a time. The alternative — recomputing "what should happen now"
on each sweep — is subtly worse in three ways:

* It cannot answer "what will happen to this customer next, and when", which is
  the first question support asks on a past-due account.
* It makes changing a policy retroactive. A customer who entered dunning under
  a 14-day grace period should keep it, not silently inherit whatever finance
  changed the policy to yesterday.
* It has no natural idempotency. Persisted attempts give the worker something
  to claim, so a sweep that runs twice does not send two reminder emails.

Suspension here means loss of *access*, not deletion. `Subscription.status`
moves to PAST_DUE and the tenant is deactivated; every row survives, because a
customer who pays on day 30 must get their data back intact.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .dunning_models import (
    DEFAULT_RETRY_OFFSETS,
    LIVE_CASE_STATUSES,
    DunningAttempt,
    DunningAttemptKind,
    DunningAttemptOutcome,
    DunningCase,
    DunningCaseStatus,
    DunningPolicy,
)
from .models import Payment, PaymentMethod, PaymentStatus, Subscription, SubscriptionStatus

logger = logging.getLogger("ledgerflow.billing.dunning")


class DunningError(Exception):
    """Raised for dunning operations invalid in the current state."""


# --------------------------------------------------------------------- policy
def resolve_policy(*, subscription: Subscription) -> DunningPolicy | None:
    """Pick the policy governing a subscription: plan-specific, else default."""
    specific = (
        DunningPolicy.objects.filter(is_active=True, applies_to_plans=subscription.plan_id)
        .order_by("name")
        .first()
    )
    if specific is not None:
        return specific
    return DunningPolicy.objects.filter(is_active=True, is_default=True).first()


def ensure_default_policy() -> DunningPolicy:
    """Get-or-create the fallback policy.

    A deployment that has never opened the dunning settings screen should still
    recover failed payments; requiring configuration before the engine works at
    all would mean the feature silently does nothing on a fresh install.
    """
    policy = DunningPolicy.objects.filter(is_default=True).first()
    if policy is not None:
        return policy
    return DunningPolicy.objects.create(
        name="Standard recovery",
        description="Default retry and reminder schedule.",
        retry_offsets_days=list(DEFAULT_RETRY_OFFSETS),
        reminder_offsets_days=[1, 7, 14],
        grace_period_days=14,
        suspend_after_days=21,
        abandon_after_days=45,
        is_default=True,
    )


def validate_policy(policy: DunningPolicy) -> None:
    """Reject schedules that cannot happen in the order they claim.

    Raised as a domain error so an operator editing a policy gets a sentence,
    not a constraint violation.
    """
    if policy.suspend_after_days < policy.grace_period_days:
        raise DunningError("Suspension cannot happen before the grace period ends.")
    if policy.abandon_after_days < policy.suspend_after_days:
        raise DunningError("A case cannot be abandoned before it is suspended.")
    for offset in policy.retries:
        if offset < 0:
            raise DunningError("Retry offsets must be zero or more days after the failure.")


# ----------------------------------------------------------------------- cases
@transaction.atomic
def open_case(
    *,
    subscription: Subscription,
    invoice=None,
    amount_minor: int | None = None,
    failure_reason: str = "",
    policy: DunningPolicy | None = None,
    now=None,
) -> DunningCase:
    """Start recovery for a failed payment, writing the whole schedule.

    Idempotent: a subscription already in an open case returns that case. Two
    failure webhooks arriving together must not produce two reminder sequences,
    and the partial unique index makes that a guarantee rather than a hope.
    """
    now = now or timezone.now()

    existing = DunningCase.objects.filter(subscription=subscription, status__in=LIVE_CASE_STATUSES).first()
    if existing is not None:
        return existing

    policy = policy or resolve_policy(subscription=subscription) or ensure_default_policy()
    validate_policy(policy)

    case = DunningCase.objects.create(
        tenant_id=subscription.tenant_id,
        subscription=subscription,
        invoice=invoice,
        policy=policy,
        status=DunningCaseStatus.OPEN,
        amount_minor=amount_minor if amount_minor is not None else subscription.plan.price_minor,
        currency=subscription.plan.currency,
        opened_at=now,
        grace_ends_at=now + timedelta(days=policy.grace_period_days),
        suspend_at=now + timedelta(days=policy.suspend_after_days),
        last_failure_reason=failure_reason[:255],
    )
    _schedule(case=case, policy=policy, now=now)
    logger.info("dunning case opened for subscription %s", subscription.id)
    return case


def _schedule(*, case: DunningCase, policy: DunningPolicy, now) -> None:
    """Write every attempt the policy calls for."""
    attempts: list[DunningAttempt] = []

    for index, offset in enumerate(policy.retries, start=1):
        attempts.append(
            DunningAttempt(
                case=case,
                kind=DunningAttemptKind.RETRY,
                sequence=index,
                scheduled_for=now + timedelta(days=offset),
            )
        )

    if policy.send_email:
        for index, offset in enumerate(policy.reminders, start=1):
            attempts.append(
                DunningAttempt(
                    case=case,
                    kind=DunningAttemptKind.REMINDER_EMAIL,
                    sequence=index,
                    scheduled_for=now + timedelta(days=offset),
                )
            )
    if policy.send_sms:
        for index, offset in enumerate(policy.reminders, start=1):
            attempts.append(
                DunningAttempt(
                    case=case,
                    kind=DunningAttemptKind.REMINDER_SMS,
                    sequence=index,
                    scheduled_for=now + timedelta(days=offset),
                )
            )

    attempts.append(
        DunningAttempt(
            case=case,
            kind=DunningAttemptKind.SUSPEND,
            sequence=1,
            scheduled_for=now + timedelta(days=policy.suspend_after_days),
        )
    )
    attempts.append(
        DunningAttempt(
            case=case,
            kind=DunningAttemptKind.ABANDON,
            sequence=1,
            scheduled_for=now + timedelta(days=policy.abandon_after_days),
        )
    )
    DunningAttempt.objects.bulk_create(attempts)


@transaction.atomic
def close_case(*, case: DunningCase, status: str, note: str = "", now=None) -> DunningCase:
    """Resolve a case and cancel everything still scheduled.

    Cancelling the remaining attempts is the important half: a customer who
    paid on day 3 must not receive the day-7 reminder, and must certainly not
    be suspended on day 21.
    """
    now = now or timezone.now()
    case.status = status
    case.resolved_at = now
    case.resolution_note = note[:255]
    case.save(update_fields=["status", "resolved_at", "resolution_note", "updated_at"])

    DunningAttempt.objects.filter(case=case, outcome=DunningAttemptOutcome.SCHEDULED).update(
        outcome=DunningAttemptOutcome.CANCELLED, updated_at=now
    )
    return case


@transaction.atomic
def mark_recovered(*, case: DunningCase, note: str = "Payment recovered.", now=None) -> DunningCase:
    """The happy path: money arrived, restore access, cancel the schedule."""
    now = now or timezone.now()
    subscription = case.subscription

    subscription.status = SubscriptionStatus.ACTIVE
    subscription.save(update_fields=["status", "updated_at"])
    _set_tenant_active(subscription.tenant_id, True)

    return close_case(case=case, status=DunningCaseStatus.RECOVERED, note=note, now=now)


def _set_tenant_active(tenant_id, active: bool) -> None:
    """Flip workspace access without importing tenancy at module scope.

    A local import keeps `billing` from taking a hard dependency on `tenancy`,
    preserving the one-way direction the app graph already has.
    """
    from apps.tenancy.models import Tenant

    Tenant.objects.filter(id=tenant_id).update(is_active=active, updated_at=timezone.now())


# ------------------------------------------------------------------ execution
def due_attempts(*, now=None, limit: int = 200):
    """Attempts that should run now, oldest first."""
    now = now or timezone.now()
    return (
        DunningAttempt.objects.filter(
            outcome=DunningAttemptOutcome.SCHEDULED,
            scheduled_for__lte=now,
            case__status__in=LIVE_CASE_STATUSES,
        )
        .select_related("case", "case__subscription", "case__subscription__plan", "case__policy")
        .order_by("scheduled_for")[:limit]
    )


@transaction.atomic
def execute_attempt(*, attempt: DunningAttempt, now=None) -> DunningAttempt:
    """Run one scheduled attempt.

    Claims the row with `select_for_update` and re-checks that it is still
    SCHEDULED, so two workers racing on the same sweep cannot both send the
    reminder. The loser sees a non-scheduled row and returns without acting.
    """
    now = now or timezone.now()
    attempt = DunningAttempt.objects.select_for_update().select_related("case").get(pk=attempt.pk)
    if attempt.outcome != DunningAttemptOutcome.SCHEDULED:
        return attempt

    case = attempt.case
    if not case.is_live:
        attempt.outcome = DunningAttemptOutcome.CANCELLED
        attempt.executed_at = now
        attempt.save(update_fields=["outcome", "executed_at", "updated_at"])
        return attempt

    handler = {
        DunningAttemptKind.RETRY: _run_retry,
        DunningAttemptKind.REMINDER_EMAIL: _run_reminder,
        DunningAttemptKind.REMINDER_SMS: _run_reminder,
        DunningAttemptKind.SUSPEND: _run_suspend,
        DunningAttemptKind.ABANDON: _run_abandon,
    }[attempt.kind]

    handler(attempt=attempt, case=case, now=now)
    attempt.executed_at = now
    attempt.save(update_fields=["outcome", "executed_at", "detail", "payment", "updated_at"])
    return attempt


def _run_retry(*, attempt: DunningAttempt, case: DunningCase, now) -> None:
    """Re-charge the default payment method."""
    from . import services as billing_services

    subscription = case.subscription
    method = (
        PaymentMethod.objects.filter(tenant_id=case.tenant_id, is_default=True).first()
        or PaymentMethod.objects.filter(tenant_id=case.tenant_id).order_by("-created_at").first()
    )
    if method is None:
        attempt.outcome = DunningAttemptOutcome.SKIPPED
        attempt.detail = "No payment method on file."
        return

    try:
        payment = billing_services._charge_for_subscription(
            sub=subscription, plan=subscription.plan, payment_method=method
        )
    except billing_services.BillingError as exc:
        attempt.outcome = DunningAttemptOutcome.FAILED
        attempt.detail = str(exc)[:255]
        DunningCase.objects.filter(pk=case.pk).update(
            attempts_made=case.attempts_made + 1, last_failure_reason=str(exc)[:255]
        )
        return

    attempt.payment = payment
    DunningCase.objects.filter(pk=case.pk).update(attempts_made=case.attempts_made + 1)

    if payment.status == PaymentStatus.SUCCEEDED:
        attempt.outcome = DunningAttemptOutcome.SUCCEEDED
        attempt.detail = "Payment recovered."
        mark_recovered(case=case, now=now)
    elif payment.status == PaymentStatus.PENDING:
        # An STK push is out with the customer. Neither success nor failure
        # yet; the webhook decides, and `on_payment_succeeded` closes the case.
        attempt.outcome = DunningAttemptOutcome.SUCCEEDED
        attempt.detail = "Awaiting customer confirmation."
    else:
        attempt.outcome = DunningAttemptOutcome.FAILED
        attempt.detail = (payment.failure_reason or "Declined.")[:255]


def _run_reminder(*, attempt: DunningAttempt, case: DunningCase, now) -> None:
    """Raise a platform-side notice and an in-app notice for the customer.

    Delivery beyond in-app is intentionally not this module's business: the
    notifications app already owns channel fan-out, and duplicating that here
    would give the product two places that decide whether a customer gets an
    email.
    """
    from apps.platform_admin.notifications import raise_platform_alert

    channel = "SMS" if attempt.kind == DunningAttemptKind.REMINDER_SMS else "email"
    raise_platform_alert(
        category="dunning.reminder",
        severity="info",
        title=f"Payment reminder sent ({channel})",
        body=f"Reminder {attempt.sequence} for a past-due subscription.",
        tenant_id=case.tenant_id,
        subject_type="billing.DunningCase",
        subject_id=case.id,
        dedupe_key=f"dunning:{case.id}:{attempt.kind}:{attempt.sequence}",
    )
    attempt.outcome = DunningAttemptOutcome.SUCCEEDED
    attempt.detail = f"Reminder {attempt.sequence} sent by {channel}."


def _run_suspend(*, attempt: DunningAttempt, case: DunningCase, now) -> None:
    subscription = case.subscription
    subscription.status = SubscriptionStatus.PAST_DUE
    subscription.save(update_fields=["status", "updated_at"])
    _set_tenant_active(case.tenant_id, False)

    DunningCase.objects.filter(pk=case.pk).update(status=DunningCaseStatus.SUSPENDED)
    attempt.outcome = DunningAttemptOutcome.SUCCEEDED
    attempt.detail = "Workspace suspended for non-payment."

    from apps.platform_admin.notifications import raise_platform_alert

    raise_platform_alert(
        category="dunning.suspended",
        severity="warning",
        title="Workspace suspended for non-payment",
        body=f"{case.amount_minor} {case.currency} outstanding.",
        tenant_id=case.tenant_id,
        subject_type="billing.DunningCase",
        subject_id=case.id,
        dedupe_key=f"dunning:{case.id}:suspended",
    )


def _run_abandon(*, attempt: DunningAttempt, case: DunningCase, now) -> None:
    subscription = case.subscription
    subscription.status = SubscriptionStatus.CANCELED
    subscription.canceled_at = now
    subscription.save(update_fields=["status", "canceled_at", "updated_at"])

    DunningCase.objects.filter(pk=case.pk).update(
        status=DunningCaseStatus.ABANDONED, resolved_at=now, resolution_note="Involuntary churn."
    )
    DunningAttempt.objects.filter(case=case, outcome=DunningAttemptOutcome.SCHEDULED).exclude(
        pk=attempt.pk
    ).update(outcome=DunningAttemptOutcome.CANCELLED)

    attempt.outcome = DunningAttemptOutcome.SUCCEEDED
    attempt.detail = "Case abandoned; subscription cancelled."


def run_due_attempts(*, now=None, limit: int = 200) -> dict[str, int]:
    """Sweep entry point. Returns a small summary for the task log.

    Each attempt runs in its own transaction (via `execute_attempt`) so one
    provider timeout does not roll back the reminders that already succeeded.
    """
    now = now or timezone.now()
    summary = {"executed": 0, "succeeded": 0, "failed": 0, "skipped": 0}
    for attempt in list(due_attempts(now=now, limit=limit)):
        try:
            result = execute_attempt(attempt=attempt, now=now)
        except Exception:  # pragma: no cover - defensive
            logger.exception("dunning attempt %s raised", attempt.pk)
            summary["failed"] += 1
            continue
        summary["executed"] += 1
        if result.outcome == DunningAttemptOutcome.SUCCEEDED:
            summary["succeeded"] += 1
        elif result.outcome == DunningAttemptOutcome.FAILED:
            summary["failed"] += 1
        elif result.outcome == DunningAttemptOutcome.SKIPPED:
            summary["skipped"] += 1
    return summary


# --------------------------------------------------------------------- hooks
def on_payment_failed(*, payment: Payment, reason: str = "") -> DunningCase | None:
    """Called when a subscription payment fails. Opens or updates a case."""
    subscription = payment.subscription
    if subscription is None or subscription.plan.price_minor == 0:
        return None
    return open_case(
        subscription=subscription,
        amount_minor=payment.amount_minor,
        failure_reason=reason or payment.failure_reason,
    )


def on_payment_succeeded(*, payment: Payment) -> DunningCase | None:
    """Called when money arrives. Closes any open case for that subscription.

    Covers the case where the customer fixes their card themselves in the
    billing UI — recovery is not only something the retry schedule can achieve,
    and a customer who has paid must not keep receiving dunning mail.
    """
    subscription = payment.subscription
    if subscription is None:
        return None
    case = DunningCase.objects.filter(subscription=subscription, status__in=LIVE_CASE_STATUSES).first()
    if case is None:
        return None
    return mark_recovered(case=case, note="Payment received.")
