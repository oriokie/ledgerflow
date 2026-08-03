"""Tests for savings goals: manual + account-balance tracking, achievement."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from apps.finance import services as finance_services
from apps.finance.models import AccountType
from apps.goals import selectors, services
from apps.goals.models import GoalStatus, GoalTracking
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def test_manual_goal_progress_from_contributions():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        goal = services.create_goal(name="Vacation", currency="USD", target_minor=100000)
        services.add_contribution(goal=goal, amount_minor=30000)
        services.add_contribution(goal=goal, amount_minor=20000)
        status = selectors.goal_status(goal)
        assert status.saved_minor == 50000
        assert status.remaining_minor == 50000
        assert status.percent == 50.0
        assert not status.is_met


def test_goal_marked_achieved_when_target_reached():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        goal = services.create_goal(name="Laptop", currency="USD", target_minor=100000)
        services.add_contribution(goal=goal, amount_minor=100000)
        goal.refresh_from_db()
        assert goal.status == GoalStatus.ACHIEVED
        assert goal.achieved_at is not None


def test_account_balance_goal_tracks_linked_account():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        savings = finance_services.create_financial_account(
            name="Savings", account_type=AccountType.SAVINGS, currency="USD"
        )
        goal = services.create_goal(
            name="Emergency fund",
            currency="USD",
            target_minor=500000,
            tracking=GoalTracking.ACCOUNT_BALANCE,
            linked_account=savings,
        )
        # a manual contribution is rejected for account-balance goals
        with pytest.raises(services.GoalError):
            services.add_contribution(goal=goal, amount_minor=1000)
        # progress reflects the (currently zero) account balance
        assert selectors.goal_status(goal).saved_minor == 0


def test_account_balance_goal_requires_linked_account():
    tid = uuid.uuid4()
    with tenant_scope(tid), pytest.raises(services.GoalError):
        services.create_goal(
            name="No account",
            currency="USD",
            target_minor=1000,
            tracking=GoalTracking.ACCOUNT_BALANCE,
        )


def test_required_monthly_contribution():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        target = date.today().replace(day=1)
        # ~3 months out
        far = (target + timedelta(days=95)).replace(day=1)
        goal = services.create_goal(name="Trip", currency="USD", target_minor=90000, target_date=far)
        services.add_contribution(goal=goal, amount_minor=30000)
        status = selectors.goal_status(goal)
        monthly = status.required_monthly_minor(as_of=target)
        assert monthly is not None and monthly > 0


def test_archived_goal_excluded_from_default_list():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        services.create_goal(name="Keep", currency="USD", target_minor=1000)
        g2 = services.create_goal(name="Drop", currency="USD", target_minor=1000)
        services.archive_goal(goal=g2)
        names = {g.name for g in selectors.list_goals()}
        assert "Keep" in names and "Drop" not in names
        names_all = {g.name for g in selectors.list_goals(include_archived=True)}
        assert "Drop" in names_all
