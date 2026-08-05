"""The smart budget: a first draft assembled from what the workspace knows.

The properties tested hardest, because each one is a way the feature could be
confidently wrong:

* medians, not means — one car repair must not become a permanent line
* commitments are floors — a line never proposes less than its recurring bills
* savings goals are funded *before* discretionary history — that ordering is
  the entire promise ("stay afloat and meet your goals"), and reversing it
  would silently turn the feature into a drift-documenting machine
* an unaffordable situation is reported, never papered over
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.budgeting import smart
from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind
from apps.income.models import IncomeSource
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db

AS_OF = date(2026, 8, 4)


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _account(name="Checking"):
    # Funded well past anything these fixtures spend. They post months of
    # history without the matching income, so a realistic opening balance would
    # run the account dry and trip the overdraft guard — which is a fact about
    # the fixture, not about the budget maths under test.
    return finance_services.create_financial_account(
        name=name, account_type=AccountType.CHECKING, currency="USD", opening_balance_minor=100_000_000
    )


def _category(name, kind=CategoryKind.EXPENSE):
    return finance_services.create_category(name=name, kind=kind, currency="USD")


def _spend(account, category, amount_minor, on: date):
    finance_services.record_expense(
        financial_account=account,
        category=category,
        amount_minor=amount_minor,
        occurred_at=datetime(on.year, on.month, on.day, 12, tzinfo=UTC),
    )


def _salary(net_minor=500_000):
    return IncomeSource.objects.create(
        name="Salary",
        kind="employment",
        currency="USD",
        net_minor=net_minor,
        reliability="fixed",
        frequency="monthly",
        starts_on=date(2025, 1, 1),
    )


def _history(account, category, amounts_by_month: list[int]):
    """One spend per trailing complete month, oldest first."""
    for i, amount in enumerate(reversed(amounts_by_month)):
        month_anchor = smart._months_back(AS_OF.replace(day=1), i + 1)
        _spend(account, category, amount, month_anchor.replace(day=15))


def test_the_proposal_uses_the_median_not_the_mean(tenant):
    """May: 20k. June: 20k. July: 90k (the car broke). A mean would budget
    43k/mo for transport forever; the median says 20k."""
    with tenant_scope(tenant):
        account = _account()
        transport = _category("Transport")
        _salary()
        _history(account, transport, [20_000, 20_000, 90_000])

        proposal = smart.propose_budget(as_of=AS_OF)

    (line,) = [ln for ln in proposal.lines if ln.category_name == "Transport"]
    assert line.limit_minor == 20_000


def test_a_single_appearance_is_an_event_not_a_habit(tenant):
    with tenant_scope(tenant):
        account = _account()
        groceries = _category("Groceries")
        wedding = _category("Wedding gift")
        _salary()
        _history(account, groceries, [30_000, 32_000, 31_000])
        _spend(account, wedding, 15_000, smart._months_back(AS_OF.replace(day=1), 1).replace(day=3))

        proposal = smart.propose_budget(as_of=AS_OF)

    names = [ln.category_name for ln in proposal.lines]
    assert "Groceries" in names
    assert "Wedding gift" not in names


def test_recurring_bills_floor_their_category(tenant):
    """History says rent was 80k; the lease says 100k from next month. The
    commitment wins — proposing under it is a plan to fail."""
    from apps.finance.models import Bill

    with tenant_scope(tenant):
        account = _account()
        housing = _category("Housing")
        _salary(1_000_000)
        _history(account, housing, [80_000, 80_000, 80_000])
        Bill.objects.create(
            name="Rent",
            category=housing,
            amount_minor=100_000,
            currency="USD",
            due_on=AS_OF + timedelta(days=10),
            recurrence_frequency="monthly",
        )

        proposal = smart.propose_budget(as_of=AS_OF)

    (line,) = [ln for ln in proposal.lines if ln.category_name == "Housing"]
    assert line.limit_minor >= 100_000
    assert line.floor_minor == 100_000


def test_savings_goals_are_funded_before_discretionary_spending(tenant):
    """Income 500k. History spends 480k. Goals need 100k/mo. The proposal must
    trim history to ~400k rather than shrug at the goal — this ordering is the
    feature's entire reason to exist."""
    from apps.goals.models import SavingsGoal

    with tenant_scope(tenant):
        account = _account()
        dining = _category("Dining out")
        groceries = _category("Groceries")
        _salary(500_000)
        _history(account, dining, [240_000, 240_000, 240_000])
        _history(account, groceries, [240_000, 240_000, 240_000])
        SavingsGoal.objects.create(
            name="Emergency fund",
            currency="USD",
            target_minor=1_200_000,
            planned_monthly_minor=100_000,
        )

        proposal = smart.propose_budget(as_of=AS_OF)

    assert proposal.savings_target_minor == 100_000
    assert proposal.envelope_minor == 400_000
    assert proposal.total_minor <= 400_000
    assert 0 < proposal.trim_factor < 1
    for line in proposal.lines:
        assert "savings goals" in line.rationale


def test_a_budget_that_fits_is_not_trimmed(tenant):
    with tenant_scope(tenant):
        account = _account()
        groceries = _category("Groceries")
        _salary(500_000)
        _history(account, groceries, [100_000, 100_000, 100_000])

        proposal = smart.propose_budget(as_of=AS_OF)

    assert proposal.trim_factor == 1.0
    assert proposal.left_over_minor > 0


def test_commitments_beyond_income_are_reported_not_hidden(tenant):
    """Floors above the envelope: no trim can fix that. The proposal must say
    deficit rather than produce tidy numbers that cannot work."""
    from apps.finance.models import Bill

    with tenant_scope(tenant):
        account = _account()
        housing = _category("Housing")
        _salary(100_000)
        _history(account, housing, [90_000, 90_000, 90_000])
        Bill.objects.create(
            name="Rent",
            category=housing,
            amount_minor=150_000,
            currency="USD",
            due_on=AS_OF + timedelta(days=10),
            recurrence_frequency="monthly",
        )

        proposal = smart.propose_budget(as_of=AS_OF)

    assert proposal.deficit is True
    (line,) = [ln for ln in proposal.lines if ln.category_name == "Housing"]
    assert line.limit_minor == 150_000  # held at the commitment, not trimmed


def test_without_income_history_still_proposes_but_says_income_unknown(tenant):
    """A household that has not recorded income still gets a draft from its
    history — but nothing is trimmed, because there is no envelope to trim to."""
    with tenant_scope(tenant):
        account = _account()
        groceries = _category("Groceries")
        _history(account, groceries, [50_000, 52_000, 51_000])

        proposal = smart.propose_budget(as_of=AS_OF)

    assert proposal.income_known is False
    assert proposal.trim_factor == 1.0


def test_an_empty_workspace_raises_rather_than_proposing_nothing(tenant):
    with tenant_scope(tenant), pytest.raises(smart.NothingToProposeError):
        smart.propose_budget(as_of=AS_OF)


def test_the_current_partial_month_is_ignored(tenant):
    """Half a month of spending looks like frugality. The window must end at
    the first of the current month."""
    with tenant_scope(tenant):
        account = _account()
        groceries = _category("Groceries")
        _salary()
        _history(account, groceries, [50_000, 50_000, 50_000])
        _spend(account, groceries, 5_000, AS_OF - timedelta(days=1))  # this month

        proposal = smart.propose_budget(as_of=AS_OF)

    (line,) = [ln for ln in proposal.lines if ln.category_name == "Groceries"]
    assert line.limit_minor == 50_000


def test_limits_are_rounded_to_whole_units(tenant):
    with tenant_scope(tenant):
        account = _account()
        groceries = _category("Groceries")
        _salary()
        _history(account, groceries, [49_957, 50_013, 50_101])

        proposal = smart.propose_budget(as_of=AS_OF)

    (line,) = [ln for ln in proposal.lines if ln.category_name == "Groceries"]
    assert line.limit_minor % 100 == 0


def test_apply_creates_a_real_budget_with_the_proposed_lines(tenant):
    from apps.budgeting.models import BudgetLine

    with tenant_scope(tenant):
        account = _account()
        groceries = _category("Groceries")
        _salary()
        _history(account, groceries, [50_000, 50_000, 50_000])

        proposal = smart.propose_budget(as_of=AS_OF)
        budget = smart.apply_proposal(proposal)

        lines = list(BudgetLine.objects.filter(budget=budget))

    assert budget.starts_on == date(2026, 8, 1)
    assert len(lines) == len(proposal.lines)
    assert lines[0].limit_minor == 50_000


# ------------------------------------------------------------------- API
def test_api_returns_a_proposal(tenant_context):
    membership, client = tenant_context
    with tenant_scope(membership.tenant_id):
        account = _account()
        groceries = _category("Groceries")
        _salary()
        _history(account, groceries, [50_000, 50_000, 50_000])

    resp = client.get("/api/v1/budgeting/budgets/suggest/")
    assert resp.status_code == 200, resp.data
    assert resp.data["lines"][0]["category_name"] == "Groceries"
    assert resp.data["lines"][0]["rationale"]


def test_api_apply_creates_the_budget(tenant_context):
    membership, client = tenant_context
    with tenant_scope(membership.tenant_id):
        account = _account()
        groceries = _category("Groceries")
        _salary()
        _history(account, groceries, [50_000, 50_000, 50_000])

    resp = client.post("/api/v1/budgeting/budgets/suggest/", {}, format="json")
    assert resp.status_code == 201, resp.data
    assert resp.data["budget"]["id"]


def test_api_with_nothing_to_propose_is_a_404_not_a_500(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/budgeting/budgets/suggest/")
    assert resp.status_code == 404
    assert "detail" in resp.data
