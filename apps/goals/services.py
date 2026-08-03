"""Savings-goal service layer.

Goals never post to the ledger — money doesn't move when a goal is created or a
contribution logged. These services just maintain the goal aggregate and its
contributions, and flip a goal to ACHIEVED when it crosses its target. Progress
*reads* live in selectors.
"""

from __future__ import annotations

import logging
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.common.outbox import OutboxEvent

from .models import (
    DEFAULT_PRIORITY_BY_KIND,
    GoalContribution,
    GoalKind,
    GoalStatus,
    GoalTracking,
    SavingsGoal,
)

logger = logging.getLogger("ledgerflow.goals")


def _goal_owner(goal: SavingsGoal):
    """Best-effort recipient for a goal notification: the user who created it.
    Returns None if unknown, which makes the notification workspace-wide."""
    from apps.users.models import User

    if goal.created_by_id is None:
        return None
    return User.objects.filter(id=goal.created_by_id).first()


class GoalError(Exception): ...


@transaction.atomic
def create_goal(
    *,
    name: str,
    currency: str,
    target_minor: int,
    target_date: date | None = None,
    tracking: str = GoalTracking.MANUAL,
    linked_account=None,
    notes: str = "",
    kind: str = GoalKind.CUSTOM,
    priority: int | None = None,
    planned_monthly_minor: int | None = None,
) -> SavingsGoal:
    if target_minor <= 0:
        raise GoalError("Goal target must be positive.")
    if tracking == GoalTracking.ACCOUNT_BALANCE and linked_account is None:
        raise GoalError("account_balance tracking requires a linked_account.")
    if linked_account is not None and linked_account.currency != currency:
        raise GoalError("Linked account currency must match the goal currency.")
    if planned_monthly_minor is not None and planned_monthly_minor <= 0:
        raise GoalError("Planned monthly contribution must be positive.")

    goal = SavingsGoal.objects.create(
        name=name,
        kind=kind,
        currency=currency,
        target_minor=target_minor,
        target_date=target_date,
        # An unstated priority follows the kind: a safety net outranks a
        # holiday unless the user says otherwise.
        priority=priority if priority is not None else DEFAULT_PRIORITY_BY_KIND.get(kind, 3),
        tracking=tracking,
        linked_account=linked_account,
        planned_monthly_minor=planned_monthly_minor,
        notes=notes,
    )
    OutboxEvent.objects.create(
        tenant_id=goal.tenant_id,
        aggregate_type="goals.SavingsGoal",
        aggregate_id=goal.id,
        event_type="goals.goal.created",
        payload={"name": name, "kind": kind, "target_minor": target_minor, "currency": currency},
    )
    return goal


@transaction.atomic
def update_goal(*, goal: SavingsGoal, **fields) -> SavingsGoal:
    """Updates a goal's plan and presentation.

    `currency` and `tracking` are intentionally not updatable: both change the
    meaning of every contribution already recorded against the goal, so
    changing them would silently reinterpret history rather than correct it.
    """
    allowed = {
        "name",
        "kind",
        "target_minor",
        "target_date",
        "priority",
        "planned_monthly_minor",
        "notes",
        "status",
    }
    changed: list[str] = []
    for key, value in fields.items():
        if key not in allowed or value is None:
            continue
        if key == "target_minor" and value <= 0:
            raise GoalError("Goal target must be positive.")
        if key == "planned_monthly_minor" and value <= 0:
            raise GoalError("Planned monthly contribution must be positive.")
        setattr(goal, key, value)
        changed.append(key)
    if changed:
        goal.save(update_fields=[*changed, "updated_at"])
        # A raised or lowered target can cross the achievement line either way.
        _maybe_mark_achieved(goal)
    return goal


@transaction.atomic
def set_auto_contribution(
    *,
    goal: SavingsGoal,
    enabled: bool,
    amount_minor: int | None = None,
    day_of_month: int | None = None,
) -> SavingsGoal:
    """Configures the standing monthly contribution for a goal.

    This records money the user has already arranged to set aside — a standing
    order into their savings account, say. It deliberately does **not** move
    money: a goal is a lens over existing funds, not a ledger construct, and
    inventing transfers the bank never made would corrupt reconciliation.
    """
    if goal.tracking != GoalTracking.MANUAL:
        raise GoalError("Auto contributions only apply to manual-tracking goals.")
    if enabled:
        if not amount_minor or amount_minor <= 0:
            raise GoalError("Auto contribution needs a positive amount.")
        if day_of_month is None or not (1 <= day_of_month <= 28):
            # Capped at 28 so the instruction fires in every month, February
            # included — the alternative silently skips days 29–31.
            raise GoalError("Auto contribution day must be between 1 and 28.")

    goal.auto_contribute_enabled = enabled
    goal.auto_contribute_minor = amount_minor if enabled else None
    goal.auto_contribute_day = day_of_month if enabled else None
    goal.save(
        update_fields=[
            "auto_contribute_enabled",
            "auto_contribute_minor",
            "auto_contribute_day",
            "updated_at",
        ]
    )
    return goal


def run_due_auto_contributions(*, as_of: date | None = None) -> int:
    """Materialises this month's automatic contributions. Returns the count.

    Idempotent by month: `auto_contribute_last_run_on` is checked before each
    post, so running twice on the same day — or catching up after an outage —
    can never double-fund a goal. Called by a scheduled task; safe to invoke by
    hand.
    """
    as_of = as_of or timezone.localdate()
    month_start = as_of.replace(day=1)

    due = SavingsGoal.objects.filter(
        status=GoalStatus.ACTIVE,
        tracking=GoalTracking.MANUAL,
        auto_contribute_enabled=True,
        auto_contribute_day__lte=as_of.day,
    ).exclude(auto_contribute_last_run_on__gte=month_start)

    posted = 0
    for goal in due:
        if not goal.auto_contribute_minor:
            continue
        with transaction.atomic():
            add_contribution(
                goal=goal,
                amount_minor=goal.auto_contribute_minor,
                occurred_on=as_of,
                memo="Automatic contribution",
            )
            goal.auto_contribute_last_run_on = as_of
            goal.save(update_fields=["auto_contribute_last_run_on", "updated_at"])
        posted += 1
    return posted


@transaction.atomic
def add_contribution(
    *,
    goal: SavingsGoal,
    amount_minor: int,
    occurred_on: date | None = None,
    memo: str = "",
    source_transaction=None,
    from_account=None,
    to_account=None,
) -> GoalContribution:
    """Record an amount set aside toward a manual-tracking goal.

    Two honest modes, and the caller chooses by whether they name a source:

    * **Unfunded** (no ``from_account``) — the historical behaviour, and still
      the default. The user has *already* moved the money by their own means,
      or the savings sit commingled in an account they haven't split out. The
      contribution is pure bookkeeping over money that already exists, and no
      balance changes. This is what "a goal is a lens, not a ledger construct"
      means, and nothing here weakens it.

    * **Funded** (``from_account`` given) — the user is asking us to move the
      money *now*. We post a real transfer from that account into the goal's
      destination and hang the contribution off it via ``source_transaction``.
      The source balance genuinely drops, because the money genuinely left.

    The distinction matters because the two record different facts. Logging an
    unfunded contribution when money actually moved understates the source
    account; posting a transfer when it didn't invents one. Making the caller
    say which is the only way to keep both truthful, so funding is opt-in and
    explicit rather than inferred.

    A transfer moves money between two accounts the user already owns, so net
    worth is unchanged and reports exclude it — earmarking savings must never
    read as spending.
    """
    if goal.tracking != GoalTracking.MANUAL:
        raise GoalError("Contributions only apply to manual-tracking goals.")
    if amount_minor <= 0:
        raise GoalError("Contribution amount must be positive.")

    if from_account is not None:
        if source_transaction is not None:
            raise GoalError("Provide either a funding account or a source transaction, not both.")

        destination = to_account or goal.linked_account
        if destination is None:
            raise GoalError(
                "Link an account to this goal, or choose where the money is going, "
                "before funding a contribution."
            )
        if destination.id == from_account.id:
            raise GoalError("The money has to move somewhere other than where it already is.")
        # Cross-currency funding would need an FX rate and a gain/loss posting;
        # refusing is better than silently transferring at par.
        if from_account.currency != goal.currency or destination.currency != goal.currency:
            raise GoalError(
                f"Funding accounts must be held in {goal.currency}, matching the goal."
            )

        from apps.finance import services as finance_services

        _out_txn, _in_txn = finance_services.record_transfer(
            from_account=from_account,
            to_account=destination,
            amount_minor=amount_minor,
            occurred_at=timezone.now(),
            memo=memo or f"Contribution to {goal.name}",
        )
        # The outgoing leg is the provenance: it's the side that answers
        # "where did this money come from?".
        source_transaction = _out_txn

    contribution = GoalContribution.objects.create(
        goal=goal,
        amount_minor=amount_minor,
        occurred_on=occurred_on or timezone.localdate(),
        memo=memo,
        source_transaction=source_transaction,
    )
    _maybe_mark_achieved(goal)
    return contribution


@transaction.atomic
def archive_goal(*, goal: SavingsGoal) -> SavingsGoal:
    goal.status = GoalStatus.ARCHIVED
    goal.save(update_fields=["status", "updated_at"])
    return goal


def _maybe_mark_achieved(goal: SavingsGoal) -> None:
    """Flip a goal to ACHIEVED the first time progress reaches the target.
    Idempotent: an already-achieved goal is left alone, and progress dropping
    back below target (a reversed contribution) does not un-achieve it — a goal
    reached is a milestone that happened, not a live gauge.
    """
    from .selectors import goal_progress_minor

    if goal.status != GoalStatus.ACTIVE:
        return
    if goal_progress_minor(goal) >= goal.target_minor:
        goal.status = GoalStatus.ACHIEVED
        goal.achieved_at = timezone.now()
        goal.save(update_fields=["status", "achieved_at", "updated_at"])
        OutboxEvent.objects.create(
            tenant_id=goal.tenant_id,
            aggregate_type="goals.SavingsGoal",
            aggregate_id=goal.id,
            event_type="goals.goal.achieved",
            payload={"name": goal.name, "target_minor": goal.target_minor},
        )
        try:
            from apps.notifications import services as notif_services

            notif_services.notify_goal_achieved(goal, user=_goal_owner(goal))
        except Exception:  # noqa: BLE001 - a notification failure must not break the goal
            logger.exception("goal-achieved notification failed", extra={"goal_id": str(goal.id)})
