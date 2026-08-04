"""Notification services — raise (idempotently) and mark read.

`raise_notification` is the single producer entry point. It's idempotent on
`dedupe_key`: raising the same alert twice (two budget evaluations in one day)
updates the existing row instead of spamming the inbox. Preference checks
(muted types) happen here so no producer can bypass them.

Higher-level producers (`evaluate_budget_alerts`, `notify_large_transaction`,
`notify_anomalies`, `notify_goal_achieved`, `evaluate_bill_alerts`) translate an
engine signal into the right notification(s). They read the signals the rest of
the system already computes — they don't recompute finance logic.
"""

from __future__ import annotations

import logging
from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (
    Notification,
    NotificationPreference,
    NotificationSeverity,
    NotificationType,
    PushSubscription,
)

logger = logging.getLogger("ledgerflow.notifications")


def _muted(user, type_: str) -> bool:
    if user is None:
        return False
    pref = NotificationPreference.objects.filter(user=user).first()
    return bool(pref and type_ in (pref.muted_types or []))


@transaction.atomic
def raise_notification(
    *,
    type: str,
    title: str,
    body: str = "",
    user=None,
    severity: str = NotificationSeverity.INFO,
    subject_type: str = "",
    subject_id=None,
    dedupe_key: str = "",
    data: dict | None = None,
) -> Notification | None:
    """Create (or refresh) a notification. Returns None if the recipient has
    muted this type. Idempotent on `dedupe_key` within a tenant."""
    if _muted(user, type):
        return None

    if dedupe_key:
        existing = Notification.objects.filter(dedupe_key=dedupe_key).first()
        if existing is not None:
            # refresh the content in place (e.g. budget went 90% -> 105%)
            existing.title = title
            existing.body = body
            existing.severity = severity
            existing.data = data or {}
            existing.save(update_fields=["title", "body", "severity", "data", "updated_at"])
            return existing

    try:
        notification = Notification.objects.create(
            user=user,
            type=type,
            severity=severity,
            title=title,
            body=body,
            subject_type=subject_type,
            subject_id=subject_id,
            dedupe_key=dedupe_key,
            data=data or {},
            delivered_channels=["inapp"],
        )
        _dispatch_push(notification)
        # Email is opt-in and queued after commit; see email_channel for why
        # both of those are deliberate.
        from .email_channel import dispatch_email

        dispatch_email(notification)
        return notification
    except IntegrityError:
        # lost a race on the dedupe unique constraint — fetch the winner
        return Notification.objects.filter(dedupe_key=dedupe_key).first()


# --------------------------------------------------------------- push subscriptions
@transaction.atomic
def subscribe_to_push(
    *, user, endpoint: str, p256dh_key: str, auth_key: str, user_agent: str = ""
) -> PushSubscription:
    """Register a browser for push, or refresh an existing registration.

    Keyed on `endpoint`: the browser hands out a fresh one per subscription,
    and the same device re-subscribing — a cleared cache, a reinstalled PWA —
    updates the existing row rather than piling up a duplicate that silently
    goes stale (and un-expires it, since a fresh subscribe from the browser is
    proof the endpoint works again).
    """
    subscription, _ = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": user,
            "p256dh_key": p256dh_key,
            "auth_key": auth_key,
            "user_agent": user_agent[:255],
            "expired_at": None,
        },
    )
    return subscription


def unsubscribe_from_push(*, endpoint: str) -> bool:
    """Remove a subscription — the user turned push off, or the browser told
    us this endpoint is gone. Idempotent: unsubscribing twice is a no-op, not
    an error.

    `PushSubscription` is soft-deletable, so its queryset overrides `.delete()`
    to a bulk `.update(deleted_at=...)` — that returns a plain row count, not
    Django's default `(count, {model: count})` tuple, so it's read directly
    rather than unpacked.
    """
    updated = PushSubscription.objects.filter(endpoint=endpoint).delete()
    return updated > 0


def _dispatch_push(notification: Notification) -> None:
    """Schedule push delivery for after this transaction actually commits.

    Push delivery hooks in at this single producer choke point so every
    caller of `raise_notification` gets it automatically, rather than each of
    the five-odd producers having to remember to wire it in — the same
    reasoning as bumping the analytics cache version from the ledger's
    `post_journal_entry` rather than from each individual posting path.

    Deferred to `on_commit`: a notification that gets rolled back must not
    have already buzzed someone's phone, and firing before the row is visible
    could race a client reloading and finding nothing there yet.
    """
    from .tasks import send_push_notification

    transaction.on_commit(lambda: send_push_notification.delay(str(notification.id)))


@transaction.atomic
def mark_read(*, notification: Notification) -> Notification:
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at", "updated_at"])
    return notification


@transaction.atomic
def mark_all_read(*, user) -> int:
    return Notification.objects.filter(user=user, read_at__isnull=True).update(read_at=timezone.now())


# --------------------------------------------------------------- producers
def notify_large_transaction(txn, *, user=None) -> Notification | None:
    """Raise a large-transaction alert if the txn magnitude meets the user's
    (or default) threshold. Called from the transaction pipeline."""
    from .models import NotificationPreference

    threshold = None
    if user is not None:
        pref = NotificationPreference.objects.filter(user=user).first()
        if pref and pref.large_transaction_minor:
            threshold = pref.large_transaction_minor
    if threshold is None:
        return None
    if abs(txn.amount_minor) < threshold:
        return None
    return raise_notification(
        type=NotificationType.LARGE_TRANSACTION,
        severity=NotificationSeverity.WARNING,
        title="Large transaction recorded",
        body=f"{abs(txn.amount_minor) / 100:.2f} {txn.currency}",
        user=user,
        subject_type="transaction",
        subject_id=txn.id,
        dedupe_key=f"large_txn:{txn.id}",
        data={"amount_minor": txn.amount_minor, "currency": txn.currency},
    )


def evaluate_budget_alerts(*, as_of: date | None = None, user=None) -> list[Notification]:
    """Scan active budgets; raise a threshold or exceeded notice per line that
    has crossed. Dedupe key includes the period so each period alerts at most
    once. Reads `budgeting.selectors.budget_status` — no finance recompute."""
    from apps.budgeting.models import Budget
    from apps.budgeting.selectors import budget_status

    as_of = as_of or timezone.localdate()
    pref = NotificationPreference.objects.filter(user=user).first() if user else None
    threshold = pref.budget_threshold if pref else 0.9

    raised: list[Notification] = []
    for budget in Budget.objects.filter(is_active=True):
        for line in budget_status(budget, as_of=as_of):
            period_tag = f"{budget.id}:{line.category_id}:{as_of:%Y%m}"
            if line.over_budget:
                n = raise_notification(
                    type=NotificationType.BUDGET_EXCEEDED,
                    severity=NotificationSeverity.CRITICAL,
                    title="Budget exceeded",
                    body=f"{line.percent_used:.0f}% of limit used",
                    user=user,
                    subject_type="budget_line",
                    subject_id=line.category_id,
                    dedupe_key=f"budget_exceeded:{period_tag}",
                    data={"percent_used": line.percent_used},
                )
            elif line.percent_used >= threshold * 100:
                n = raise_notification(
                    type=NotificationType.BUDGET_THRESHOLD,
                    severity=NotificationSeverity.WARNING,
                    title="Approaching budget limit",
                    body=f"{line.percent_used:.0f}% of limit used",
                    user=user,
                    subject_type="budget_line",
                    subject_id=line.category_id,
                    dedupe_key=f"budget_threshold:{period_tag}",
                    data={"percent_used": line.percent_used},
                )
            else:
                n = None
            if n is not None:
                raised.append(n)
    return raised


def notify_goal_achieved(goal, *, user=None) -> Notification | None:
    return raise_notification(
        type=NotificationType.GOAL_ACHIEVED,
        severity=NotificationSeverity.INFO,
        title="Goal achieved 🎉",
        body=goal.name,
        user=user,
        subject_type="goal",
        subject_id=goal.id,
        dedupe_key=f"goal_achieved:{goal.id}",
        data={"target_minor": goal.target_minor, "currency": goal.currency},
    )


def notify_anomalies(anomalies, *, user=None) -> list[Notification]:
    raised = []
    for a in anomalies:
        n = raise_notification(
            type=NotificationType.ANOMALY,
            severity=NotificationSeverity.WARNING,
            title="Unusual activity detected",
            body=getattr(a, "explanation", "") or getattr(a, "kind", ""),
            user=user,
            subject_type="transaction",
            subject_id=getattr(a, "transaction_id", None),
            dedupe_key=f"anomaly:{getattr(a, 'transaction_id', '')}:{getattr(a, 'kind', '')}",
        )
        if n is not None:
            raised.append(n)
    return raised


def evaluate_bill_alerts(*, within_days: int = 7, as_of: date | None = None, user=None) -> list[Notification]:
    """Raise due-soon / overdue notices for bills. Reads the finance bills
    selector; dedupe key includes the due date so each bill alerts once per
    due cycle."""
    from apps.finance.bills import upcoming_bills
    from apps.finance.models import BillStatus

    raised: list[Notification] = []
    for ub in upcoming_bills(within_days=within_days, as_of=as_of):
        bill = ub.bill
        overdue = bill.status == BillStatus.OVERDUE or ub.days_until_due < 0
        n = raise_notification(
            type=NotificationType.BILL_OVERDUE if overdue else NotificationType.BILL_DUE,
            severity=NotificationSeverity.CRITICAL if overdue else NotificationSeverity.WARNING,
            title="Bill overdue" if overdue else "Bill due soon",
            body=f"{bill.name}: {bill.amount_minor / 100:.2f} {bill.currency} due {bill.due_on:%b %d}",
            user=user,
            subject_type="bill",
            subject_id=bill.id,
            dedupe_key=f"bill:{bill.id}:{bill.due_on:%Y%m%d}:{'overdue' if overdue else 'due'}",
            data={"amount_minor": bill.amount_minor, "due_on": bill.due_on.isoformat()},
        )
        if n is not None:
            raised.append(n)
    return raised
