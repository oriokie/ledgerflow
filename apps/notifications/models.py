"""In-app notifications & alerts.

A notification is a durable, per-user record ("your grocery budget is 90%
spent", "unusual $480 charge at ACME", "you hit your vacation goal"). The model
is delivery-agnostic: rows are created by the service layer and read back via
the API for an in-app inbox. An email/push channel can consume the same rows
later (a `delivered_channels` list tracks fan-out) without changing producers.

Notifications are generated from signals the engine *already* computes — budget
status, anomalies, goal achievement, upcoming bills — so this module is mostly
delivery plumbing, not new analysis. Producers live in `services.py`; the
`NotificationType` enum is the closed vocabulary of what can be raised.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import SoftDeletableModel


class NotificationType(models.TextChoices):
    BUDGET_THRESHOLD = "budget_threshold", "Budget threshold reached"
    BUDGET_EXCEEDED = "budget_exceeded", "Budget exceeded"
    LOW_BALANCE = "low_balance", "Low account balance"
    LARGE_TRANSACTION = "large_transaction", "Large transaction"
    ANOMALY = "anomaly", "Unusual activity"
    BILL_DUE = "bill_due", "Bill due soon"
    BILL_OVERDUE = "bill_overdue", "Bill overdue"
    GOAL_ACHIEVED = "goal_achieved", "Goal achieved"
    GOAL_MILESTONE = "goal_milestone", "Goal milestone"


class NotificationSeverity(models.TextChoices):
    INFO = "info", "Info"
    WARNING = "warning", "Warning"
    CRITICAL = "critical", "Critical"


class Notification(SoftDeletableModel):
    # Recipient. Nullable = a workspace-wide notice any member can see.
    user = models.ForeignKey(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    type = models.CharField(max_length=32, choices=NotificationType.choices)
    severity = models.CharField(
        max_length=10, choices=NotificationSeverity.choices, default=NotificationSeverity.INFO
    )
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=500, blank=True, default="")
    # What this is about — a soft reference (type + id), not an FK, so a
    # notification survives the referent being deleted and can point at any
    # aggregate (budget line, transaction, goal, bill).
    subject_type = models.CharField(max_length=40, blank=True, default="")
    subject_id = models.UUIDField(null=True, blank=True)
    # Idempotency: a stable key per (what happened, which period) so the same
    # alert isn't raised twice by repeated evaluations. Unique per tenant.
    dedupe_key = models.CharField(max_length=200, blank=True, default="")
    data = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    delivered_channels = models.JSONField(default=list, blank=True)  # e.g. ["inapp", "email"]

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "dedupe_key"],
                name="uniq_notification_dedupe",
                condition=~models.Q(dedupe_key=""),
            ),
        ]
        indexes = [
            # inbox: a user's unread notices, newest first (partial on unread)
            models.Index(
                fields=["tenant_id", "user", "-created_at"],
                name="notif_inbox_idx",
            ),
            models.Index(
                fields=["tenant_id", "-created_at"],
                name="notif_unread_idx",
                condition=models.Q(read_at__isnull=True),
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.type}: {self.title}"


class NotificationPreference(SoftDeletableModel):
    """Per-user opt-outs and thresholds. Absence of a row = defaults (all on).

    Kept deliberately small: a set of booleans per type plus a couple of numeric
    thresholds. Channels beyond in-app are future work; the shape leaves room.
    """

    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="notification_preferences")
    # muted notification types (list of NotificationType values)
    muted_types = models.JSONField(default=list, blank=True)
    # alert when a budget line crosses this fraction of its limit (0..1)
    budget_threshold = models.FloatField(default=0.9)
    # alert when an account's balance falls below this (minor units); null = off
    low_balance_minor = models.BigIntegerField(null=True, blank=True)
    # alert on any single transaction at/above this magnitude (minor); null = off
    large_transaction_minor = models.BigIntegerField(null=True, blank=True)
    #: Master switch for push delivery, independent of individual muted
    #: types — a user can want push off entirely while still seeing everything
    #: in-app, which the `muted_types` list alone can't express.
    push_enabled = models.BooleanField(default=True)

    #: Master switch for email delivery. Defaults **off**.
    #:
    #: Opt-in rather than opt-out because the alerts most worth emailing (a bill
    #: due, a low balance) are also the ones that get a finance app filtered to
    #: spam if they arrive unbidden — and once filtered, the useful ones go with
    #: them. A user who turns this on has told us email is welcome.
    email_enabled = models.BooleanField(default=False)
    #: Types the user wants by email specifically. Empty with `email_enabled`
    #: on means "the ones worth interrupting me for" (see EMAIL_WORTHY), not
    #: "all of them" — nine alert types arriving individually is how people
    #: learn to ignore all nine.
    email_types = models.JSONField(default=list, blank=True)
    #: Monthly summary of the previous month. Independent of alerting: it is a
    #: report someone opted into, not an interruption.
    monthly_summary = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "user"], name="uniq_notif_pref_user"),
        ]


class PushSubscription(SoftDeletableModel):
    """One browser/device registered for Web Push.

    A user can have several — a phone and a laptop both subscribed is normal —
    so this is a plain list, not a one-to-one. `endpoint` is the row's natural
    identity: the browser generates a fresh one per registration, and the same
    device re-subscribing (a cleared cache, a reinstalled PWA) should update the
    existing row rather than accumulate a duplicate that silently goes stale.
    """

    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="push_subscriptions")
    #: The push service URL the browser gave us — unique per registration,
    #: and the whole address a Web Push message is sent to.
    endpoint = models.URLField(max_length=1024)
    #: The two keys from the browser's PushSubscription.toJSON(), needed to
    #: encrypt a payload the push service can't read in transit.
    p256dh_key = models.CharField(max_length=255)
    auth_key = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255, blank=True, default="")
    last_used_at = models.DateTimeField(null=True, blank=True)
    #: Set when a send comes back permanently rejected (410 Gone/404) — the
    #: subscription has expired on the browser's side and retrying it forever
    #: would just keep failing. Kept rather than deleted so "why did push stop
    #: working on my phone" has an answer.
    expired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # Scoped to live rows only: PushSubscription is soft-deletable, and
            # an unconditioned constraint would collide the moment someone
            # unsubscribed and resubscribed the same browser — the constraint
            # would be enforced against a row the alive-only manager can no
            # longer see, turning "turn notifications back on" into a 500.
            models.UniqueConstraint(
                fields=["tenant_id", "endpoint"],
                name="uniq_push_subscription_endpoint",
                condition=models.Q(deleted_at__isnull=True),
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "user"], name="push_sub_user_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"push:{self.user_id}:{self.endpoint[-16:]}"

    @property
    def is_active(self) -> bool:
        return self.expired_at is None
