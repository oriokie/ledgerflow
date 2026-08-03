"""Savings-goal read side.

Progress is computed on read, never stored — the same discipline budgets use.
For manual goals it's the sum of live contributions; for account-balance goals
it's the linked account's current materialized balance. Either way a single
aggregate, no per-row Python loops.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Sum
from django.utils import timezone

from apps.finance.selectors import account_current_balance_minor

from .models import GoalContribution, GoalTracking, SavingsGoal


def goal_progress_minor(goal: SavingsGoal) -> int:
    if goal.tracking == GoalTracking.ACCOUNT_BALANCE:
        if goal.linked_account_id is None:
            return 0
        return max(0, account_current_balance_minor(goal.linked_account))
    agg = GoalContribution.objects.filter(goal=goal).aggregate(total=Sum("amount_minor"))
    return agg["total"] or 0


@dataclass(frozen=True, slots=True)
class GoalStatusView:
    goal: SavingsGoal
    saved_minor: int
    target_minor: int
    currency: str

    @property
    def remaining_minor(self) -> int:
        return max(0, self.target_minor - self.saved_minor)

    @property
    def percent(self) -> float:
        if self.target_minor <= 0:
            return 0.0
        return round(min(100.0, self.saved_minor / self.target_minor * 100), 1)

    @property
    def is_met(self) -> bool:
        return self.saved_minor >= self.target_minor

    def required_monthly_minor(self, *, as_of: date | None = None) -> int | None:
        """What you'd need to set aside per remaining month to hit the target
        by `target_date`. None if there's no date or it's already due/passed."""
        if self.goal.target_date is None or self.is_met:
            return None
        as_of = as_of or timezone.localdate()
        months = (self.goal.target_date.year - as_of.year) * 12 + (self.goal.target_date.month - as_of.month)
        if months <= 0:
            return None
        return -(-self.remaining_minor // months)  # ceil division


def goal_status(goal: SavingsGoal) -> GoalStatusView:
    return GoalStatusView(
        goal=goal,
        saved_minor=goal_progress_minor(goal),
        target_minor=goal.target_minor,
        currency=goal.currency,
    )


def list_goals(*, include_archived: bool = False):
    qs = SavingsGoal.objects.all()
    if not include_archived:
        qs = qs.exclude(status="archived")
    return qs.order_by("status", "target_date", "name")
