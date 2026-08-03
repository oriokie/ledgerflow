"""Budget calculation tests: period alignment, actual-vs-limit, subtree
aggregation via materialized path, and single-period rollover."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from apps.budgeting import selectors, services
from apps.budgeting.models import BudgetPeriod
from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


# --------------------------------------------------------------- period math
def test_period_bounds_monthly():
    start, end = selectors.period_bounds(
        period=BudgetPeriod.MONTHLY, starts_on=date(2026, 1, 1), as_of=date(2026, 3, 15)
    )
    assert (start, end) == (date(2026, 3, 1), date(2026, 4, 1))


def test_period_bounds_weekly():
    start, end = selectors.period_bounds(
        period=BudgetPeriod.WEEKLY, starts_on=date(2026, 1, 1), as_of=date(2026, 1, 20)
    )
    # 19 days = 2 whole weeks after the 1st -> window starting the 15th
    assert (start, end) == (date(2026, 1, 15), date(2026, 1, 22))


def test_period_bounds_before_start_returns_first_period():
    start, end = selectors.period_bounds(
        period=BudgetPeriod.MONTHLY, starts_on=date(2026, 6, 1), as_of=date(2026, 1, 1)
    )
    assert start == date(2026, 6, 1)


# --------------------------------------------------------------- status
def _seed_budget():
    checking = finance_services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency="USD"
    )
    food = finance_services.create_category(name="Food", kind=CategoryKind.EXPENSE, currency="USD")
    budget = services.create_budget(name="Monthly", currency="USD", starts_on=date(2026, 1, 1))
    line = services.add_budget_line(budget=budget, category=food, limit_minor=50000)
    return checking, food, budget, line


def test_budget_status_actual_vs_limit(tenant_id):
    with tenant_scope(tenant_id):
        checking, food, budget, _line = _seed_budget()
        finance_services.record_expense(
            financial_account=checking,
            category=food,
            amount_minor=20000,
            occurred_at=datetime(2026, 1, 10, tzinfo=UTC),
        )
        finance_services.record_expense(
            financial_account=checking,
            category=food,
            amount_minor=15000,
            occurred_at=datetime(2026, 1, 20, tzinfo=UTC),
        )
        [status] = selectors.budget_status(budget, as_of=date(2026, 1, 31))
        assert status.limit_minor == 50000
        assert status.actual_minor == 35000
        assert status.remaining_minor == 15000
        assert status.percent_used == 70.0
        assert status.over_budget is False


def test_budget_subtree_spending_rolls_up_to_parent(tenant_id):
    """Spending on a child category counts toward the parent's budget line."""
    with tenant_scope(tenant_id):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        food = finance_services.create_category(name="Food", kind=CategoryKind.EXPENSE, currency="USD")
        groceries = finance_services.create_category(
            name="Groceries", kind=CategoryKind.EXPENSE, currency="USD", parent=food
        )
        budget = services.create_budget(name="Monthly", currency="USD", starts_on=date(2026, 1, 1))
        services.add_budget_line(budget=budget, category=food, limit_minor=50000)

        # spend on the CHILD category
        finance_services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=12000,
            occurred_at=datetime(2026, 1, 5, tzinfo=UTC),
        )
        [status] = selectors.budget_status(budget, as_of=date(2026, 1, 31))
        assert status.actual_minor == 12000  # child spend counted under parent


def test_budget_over_budget_flag(tenant_id):
    with tenant_scope(tenant_id):
        checking, food, budget, _line = _seed_budget()
        finance_services.record_expense(
            financial_account=checking,
            category=food,
            amount_minor=60000,
            occurred_at=datetime(2026, 1, 10, tzinfo=UTC),
        )
        [status] = selectors.budget_status(budget, as_of=date(2026, 1, 31))
        assert status.over_budget is True
        assert status.remaining_minor == -10000


def test_spending_outside_period_not_counted(tenant_id):
    with tenant_scope(tenant_id):
        checking, food, budget, _line = _seed_budget()
        # February spend shouldn't show in the January window
        finance_services.record_expense(
            financial_account=checking,
            category=food,
            amount_minor=20000,
            occurred_at=datetime(2026, 2, 10, tzinfo=UTC),
        )
        [status] = selectors.budget_status(budget, as_of=date(2026, 1, 31))
        assert status.actual_minor == 0


def test_rollover_carries_previous_period_unspent(tenant_id):
    with tenant_scope(tenant_id):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        food = finance_services.create_category(name="Food", kind=CategoryKind.EXPENSE, currency="USD")
        budget = services.create_budget(name="Monthly", currency="USD", starts_on=date(2026, 1, 1))
        services.add_budget_line(budget=budget, category=food, limit_minor=50000, rollover=True)

        # January: spend only 30000 of 50000 -> 20000 unspent carries to Feb
        finance_services.record_expense(
            financial_account=checking,
            category=food,
            amount_minor=30000,
            occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
        )
        # February: spend 40000
        finance_services.record_expense(
            financial_account=checking,
            category=food,
            amount_minor=40000,
            occurred_at=datetime(2026, 2, 15, tzinfo=UTC),
        )
        [status] = selectors.budget_status(budget, as_of=date(2026, 2, 20))
        assert status.carried_minor == 20000  # unspent January
        assert status.effective_limit_minor == 70000  # 50000 + 20000
        assert status.actual_minor == 40000
        assert status.remaining_minor == 30000


def test_budget_line_requires_expense_category(tenant_id):
    with tenant_scope(tenant_id):
        income = finance_services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
        budget = services.create_budget(name="M", currency="USD", starts_on=date(2026, 1, 1))
        with pytest.raises(services.BudgetError):
            services.add_budget_line(budget=budget, category=income, limit_minor=1000)
