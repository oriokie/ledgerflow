"""Dunning — the recovery process for failed payments.

Three models rather than one flag on `Subscription`:

* `DunningPolicy` is configuration. Retry schedules and grace periods are the
  kind of thing a finance team wants to tune quarterly without a deploy, and
  different plans legitimately warrant different patience (a Business account
  gets a longer grace period than a Plus one). Config-over-hardcode.
* `DunningCase` is the episode. A subscription can go past-due, recover, and
  go past-due again months later; those are two distinct stories with distinct
  outcomes, and collapsing them onto the subscription row would destroy the
  history that makes "what is our involuntary churn rate" answerable.
* `DunningAttempt` is one scheduled action within a case — a retry, a reminder
  email, an SMS, a suspension. Persisting attempts *before* they execute is
  what makes the schedule inspectable ("what will happen to this customer
  next, and when") and idempotent: a worker claims a due attempt rather than
  recomputing what it thinks should happen now.

The engine deliberately writes no money. An attempt of kind RETRY invokes the
existing billing charge path; everything else is communication or access
state. Automation proposes; the payment provider disposes.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel

#: Days after failure at which each retry fires. Chosen to straddle a weekend
#: and a likely payday rather than to be evenly spaced — the common causes of a
#: declined card are a temporary hold and an empty account, and both resolve on
#: a calendar, not on a uniform interval.
DEFAULT_RETRY_OFFSETS = [1, 3, 7, 14]


class DunningPolicy(UUIDModel, TimeStampedModel):
    """Tunable recovery configuration. Exactly one row is the default."""

    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=255, blank=True, default="")

    #: Days after the initial failure at which to retry the charge.
    retry_offsets_days = models.JSONField(default=list, blank=True)
    #: Days after the initial failure at which to send a reminder.
    reminder_offsets_days = models.JSONField(default=list, blank=True)
    #: How long the customer keeps full access while past due.
    grace_period_days = models.PositiveSmallIntegerField(default=14)
    #: Days after failure at which the subscription is suspended. Should be
    #: >= grace_period_days; the service validates this rather than the model,
    #: so an operator gets an explanation instead of an IntegrityError.
    suspend_after_days = models.PositiveSmallIntegerField(default=21)
    #: Days after suspension at which the case is abandoned (involuntary churn).
    abandon_after_days = models.PositiveSmallIntegerField(default=45)

    send_email = models.BooleanField(default=True)
    send_sms = models.BooleanField(default=False)
    #: Restrict this policy to particular plans; empty = the catch-all default.
    applies_to_plans = models.ManyToManyField("billing.Plan", blank=True, related_name="dunning_policies")
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            # At most one default. A partial unique index expresses this
            # directly; the alternative (application-level "unset the others")
            # races under concurrent edits.
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="uniq_default_dunning_policy",
            )
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def retries(self) -> list[int]:
        return sorted(int(d) for d in (self.retry_offsets_days or DEFAULT_RETRY_OFFSETS))

    @property
    def reminders(self) -> list[int]:
        return sorted(int(d) for d in (self.reminder_offsets_days or []))


class DunningCaseStatus(models.TextChoices):
    OPEN = "open", "Open"
    RECOVERED = "recovered", "Recovered"
    SUSPENDED = "suspended", "Suspended"
    ABANDONED = "abandoned", "Abandoned"
    CANCELLED = "cancelled", "Cancelled"


#: Statuses in which a case is still being worked. SUSPENDED belongs here:
#: losing access is a step in the recovery process, not the end of it — the
#: customer can still pay, and if they never do the case must still progress
#: to abandonment. Treating SUSPENDED as terminal silently strands every
#: suspended account short of involuntary churn.
LIVE_CASE_STATUSES = (DunningCaseStatus.OPEN, DunningCaseStatus.SUSPENDED)


class DunningCase(UUIDModel, TimeStampedModel):
    """One episode of failed-payment recovery for one subscription."""

    tenant_id = models.UUIDField(db_index=True)
    subscription = models.ForeignKey(
        "billing.Subscription", on_delete=models.CASCADE, related_name="dunning_cases"
    )
    invoice = models.ForeignKey(
        "billing.Invoice", null=True, blank=True, on_delete=models.SET_NULL, related_name="dunning_cases"
    )
    policy = models.ForeignKey(
        DunningPolicy, null=True, blank=True, on_delete=models.SET_NULL, related_name="cases"
    )

    status = models.CharField(
        max_length=16, choices=DunningCaseStatus.choices, default=DunningCaseStatus.OPEN
    )
    amount_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="USD")

    opened_at = models.DateTimeField()
    grace_ends_at = models.DateTimeField(null=True, blank=True)
    suspend_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    #: Denormalised for the queue view — "how many times have we tried" is the
    #: first question asked of every row in the dunning list, and counting
    #: attempts per row would make that list N+1 by construction.
    attempts_made = models.PositiveSmallIntegerField(default=0)
    last_failure_reason = models.CharField(max_length=255, blank=True, default="")
    resolution_note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-opened_at"]
        constraints = [
            # A subscription has at most one live case. Without this, two
            # near-simultaneous failure webhooks would open two cases and the
            # customer would receive two parallel reminder sequences.
            models.UniqueConstraint(
                fields=["subscription"],
                condition=models.Q(status__in=["open", "suspended"]),
                name="uniq_open_dunning_case_per_subscription",
            )
        ]
        indexes = [
            models.Index(fields=["status", "-opened_at"]),
            models.Index(fields=["tenant_id", "-opened_at"]),
        ]

    def __str__(self) -> str:
        return f"dunning:{self.subscription_id} ({self.status})"

    @property
    def is_open(self) -> bool:
        return self.status == DunningCaseStatus.OPEN

    @property
    def is_live(self) -> bool:
        """Still being worked — open, or suspended and awaiting payment."""
        return self.status in LIVE_CASE_STATUSES


class DunningAttemptKind(models.TextChoices):
    RETRY = "retry", "Payment retry"
    REMINDER_EMAIL = "reminder_email", "Reminder email"
    REMINDER_SMS = "reminder_sms", "Reminder SMS"
    SUSPEND = "suspend", "Suspension"
    ABANDON = "abandon", "Abandonment"


class DunningAttemptOutcome(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"
    CANCELLED = "cancelled", "Cancelled"


class DunningAttempt(UUIDModel, TimeStampedModel):
    """One scheduled step in a case. Written ahead of execution."""

    case = models.ForeignKey(DunningCase, on_delete=models.CASCADE, related_name="attempts")
    kind = models.CharField(max_length=20, choices=DunningAttemptKind.choices)
    sequence = models.PositiveSmallIntegerField(default=1)
    scheduled_for = models.DateTimeField(db_index=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(
        max_length=16, choices=DunningAttemptOutcome.choices, default=DunningAttemptOutcome.SCHEDULED
    )
    payment = models.ForeignKey(
        "billing.Payment", null=True, blank=True, on_delete=models.SET_NULL, related_name="dunning_attempts"
    )
    detail = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["scheduled_for", "sequence"]
        constraints = [
            models.UniqueConstraint(fields=["case", "kind", "sequence"], name="uniq_dunning_attempt_step")
        ]
        indexes = [
            # The worker's claim query: due, not yet executed.
            models.Index(
                fields=["scheduled_for"],
                name="dunning_due_idx",
                condition=models.Q(outcome="scheduled"),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind}#{self.sequence} @ {self.scheduled_for:%Y-%m-%d} [{self.outcome}]"
