"""Savings goals — a target amount to reach by a date, with tracked progress.

A goal is intentionally *not* a ledger construct. Money doesn't move when you
set a goal; a goal is a lens over money that already exists. Progress can be
tracked two ways, and a goal picks one via `tracking`:

* ``manual`` — the user logs contributions explicitly (`GoalContribution`),
  e.g. "I put aside $200 toward the trip this month". Progress is the sum of
  contributions. This works even when the savings live in a commingled account.
* ``account_balance`` — progress mirrors a linked account's current balance,
  for the common "this whole savings account *is* the fund" case. No manual
  logging; the balance selector is the source of truth.

Keeping both keeps the model honest about a real ambiguity in personal finance
(is a "goal" a virtual envelope or a real account?) instead of forcing one.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import SoftDeletableModel


class GoalTracking(models.TextChoices):
    MANUAL = "manual", "Manual contributions"
    ACCOUNT_BALANCE = "account_balance", "Linked account balance"


class GoalKind(models.TextChoices):
    """First-class goal taxonomy.

    Kind is not cosmetic. It drives the recommendation engine (an emergency
    fund is sized from the user's own expenses, a house deposit is not), the
    default priority, and how a goal is talked about in the UI. `CUSTOM` is the
    honest escape hatch rather than forcing everything into a fixed list.
    """

    EMERGENCY_FUND = "emergency_fund", "Emergency fund"
    VACATION = "vacation", "Vacation"
    HOUSE_DEPOSIT = "house_deposit", "House deposit"
    EDUCATION = "education", "Education"
    RETIREMENT = "retirement", "Retirement"
    VEHICLE = "vehicle", "Vehicle purchase"
    DEBT_PAYOFF = "debt_payoff", "Debt payoff"
    CUSTOM = "custom", "Custom"


class GoalPriority(models.IntegerChoices):
    """Ordering intent when a user cannot fund everything at once.

    Integers (not labels) so ordering is a database concern rather than a
    Python one, and lower means more urgent so the natural ascending sort is
    also the funding order.
    """

    CRITICAL = 1, "Critical"
    HIGH = 2, "High"
    MEDIUM = 3, "Medium"
    LOW = 4, "Low"
    SOMEDAY = 5, "Someday"


#: Sensible starting priority per kind. A safety net outranks a holiday by
#: default; the user can always override.
DEFAULT_PRIORITY_BY_KIND: dict[str, int] = {
    GoalKind.EMERGENCY_FUND: GoalPriority.CRITICAL,
    GoalKind.DEBT_PAYOFF: GoalPriority.HIGH,
    GoalKind.RETIREMENT: GoalPriority.HIGH,
    GoalKind.HOUSE_DEPOSIT: GoalPriority.MEDIUM,
    GoalKind.EDUCATION: GoalPriority.MEDIUM,
    GoalKind.VEHICLE: GoalPriority.MEDIUM,
    GoalKind.VACATION: GoalPriority.LOW,
    GoalKind.CUSTOM: GoalPriority.MEDIUM,
}


class GoalStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    ACHIEVED = "achieved", "Achieved"
    ARCHIVED = "archived", "Archived"


class SavingsGoal(SoftDeletableModel):
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=20, choices=GoalKind.choices, default=GoalKind.CUSTOM)
    currency = models.CharField(max_length=3)
    target_minor = models.BigIntegerField()  # > 0
    target_date = models.DateField(null=True, blank=True)
    priority = models.PositiveSmallIntegerField(
        choices=GoalPriority.choices, default=GoalPriority.MEDIUM
    )
    tracking = models.CharField(max_length=20, choices=GoalTracking.choices, default=GoalTracking.MANUAL)
    # Required when tracking == account_balance; optional context otherwise
    # (e.g. "the account I intend to fund this from").
    linked_account = models.ForeignKey(
        "finance.FinancialAccount",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="savings_goals",
    )

    # --- funding plan -------------------------------------------------------
    # What the user *intends* to put in each month. Distinct from the required
    # amount (derived from target and date) and from the observed run rate
    # (derived from history). Keeping the three apart is what lets the forecast
    # say something useful: "you planned 300, you're actually doing 180, you
    # need 420".
    planned_monthly_minor = models.BigIntegerField(null=True, blank=True)

    # --- auto contribution --------------------------------------------------
    # A standing instruction to log a contribution on a given day each month.
    # This records money the user has *already* set aside by their own standing
    # order; it deliberately does not move money itself, because a goal is a
    # lens over existing money, not a ledger construct.
    auto_contribute_enabled = models.BooleanField(default=False)
    auto_contribute_minor = models.BigIntegerField(null=True, blank=True)
    auto_contribute_day = models.PositiveSmallIntegerField(null=True, blank=True)  # 1–28
    auto_contribute_last_run_on = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=12, choices=GoalStatus.choices, default=GoalStatus.ACTIVE)
    achieved_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(target_minor__gt=0), name="goal_target_positive"),
            models.CheckConstraint(
                condition=models.Q(planned_monthly_minor__isnull=True)
                | models.Q(planned_monthly_minor__gt=0),
                name="goal_planned_monthly_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(auto_contribute_minor__isnull=True)
                | models.Q(auto_contribute_minor__gt=0),
                name="goal_auto_amount_positive",
            ),
            # Capped at 28 so every month has the day — the 31st silently
            # skipping February is exactly the bug this prevents.
            models.CheckConstraint(
                condition=models.Q(auto_contribute_day__isnull=True)
                | models.Q(auto_contribute_day__gte=1, auto_contribute_day__lte=28),
                name="goal_auto_day_in_range",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="goal_status_idx"),
            # Funding order: most urgent first, then soonest deadline.
            models.Index(fields=["tenant_id", "priority", "target_date"], name="goal_priority_idx"),
            models.Index(fields=["tenant_id", "kind"], name="goal_kind_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} ({self.target_minor} {self.currency})"


class GoalContribution(SoftDeletableModel):
    """An explicit amount set aside toward a manual-tracking goal.

    Soft-deletable so a mistaken contribution can be reversed while keeping the
    history a true audit trail, matching the finance module's tagging approach.
    """

    goal = models.ForeignKey(SavingsGoal, on_delete=models.CASCADE, related_name="contributions")
    amount_minor = models.BigIntegerField()  # > 0
    occurred_on = models.DateField()
    memo = models.CharField(max_length=255, blank=True, default="")
    # Optional provenance link to a real transaction (e.g. a transfer into the
    # savings account that this contribution represents). Advisory only.
    source_transaction = models.ForeignKey(
        "finance.Transaction",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="goal_contributions",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(amount_minor__gt=0), name="goal_contribution_positive"),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "goal", "-occurred_on"], name="goal_contrib_idx"),
        ]
