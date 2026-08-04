"""Funded goal contributions — the case where earmarking actually moves money.

A goal is a lens over money that already exists, and an unfunded contribution
keeps it that way. Funding is the opt-in exception: the user names a source
account, real money leaves it, and the contribution hangs off the resulting
transfer. These tests pin both halves, because the bug they guard against is
silent in either direction — an unfunded contribution that moves money would
understate the source, and a funded one that doesn't would overstate it.
"""

from __future__ import annotations

import uuid

import pytest

from apps.finance import selectors as finance_selectors
from apps.finance import services as finance_services
from apps.finance.models import AccountType
from apps.goals import selectors, services
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def _accounts(checking_minor: int = 500_00, currency: str = "USD"):
    """A funded checking account and an empty savings account."""
    checking = finance_services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency=currency
    )
    savings = finance_services.create_financial_account(
        name="Savings", account_type=AccountType.SAVINGS, currency=currency
    )
    finance_services.set_opening_balance(financial_account=checking, amount_minor=checking_minor)
    return checking, savings


def test_an_unfunded_contribution_leaves_every_balance_alone():
    """The default path must stay a pure lens."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking, _savings = _accounts()
        goal = services.create_goal(name="Trip", currency="USD", target_minor=100_00)

        services.add_contribution(goal=goal, amount_minor=200_00)

        assert selectors.goal_status(goal).saved_minor == 200_00
        # The whole point: progress moved, money did not.
        assert finance_selectors.account_current_balance_minor(checking) == 500_00


def test_a_funded_contribution_reduces_the_source_account():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking, savings = _accounts()
        goal = services.create_goal(
            name="Emergency fund",
            currency="USD",
            target_minor=1000_00,
            linked_account=savings,
        )

        contribution = services.add_contribution(goal=goal, amount_minor=150_00, from_account=checking)

        assert finance_selectors.account_current_balance_minor(checking) == 350_00
        assert finance_selectors.account_current_balance_minor(savings) == 150_00
        assert selectors.goal_status(goal).saved_minor == 150_00
        # Provenance: the contribution points at the leg that funded it.
        assert contribution.source_transaction is not None
        assert contribution.source_transaction.financial_account_id == checking.id


def test_funding_leaves_net_worth_unchanged():
    """A transfer between two accounts the user already owns is not spending."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking, savings = _accounts()
        goal = services.create_goal(name="Car", currency="USD", target_minor=1000_00, linked_account=savings)

        before = finance_selectors.liquid_balance_minor("USD")
        services.add_contribution(goal=goal, amount_minor=200_00, from_account=checking)
        after = finance_selectors.liquid_balance_minor("USD")

        assert before == after


def test_funding_can_name_a_destination_when_the_goal_has_no_linked_account():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking, savings = _accounts()
        goal = services.create_goal(name="Wedding", currency="USD", target_minor=1000_00)

        services.add_contribution(goal=goal, amount_minor=100_00, from_account=checking, to_account=savings)

        assert finance_selectors.account_current_balance_minor(savings) == 100_00


def test_funding_without_any_destination_is_refused():
    """Better to ask than to guess where someone's money should land."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking, _savings = _accounts()
        goal = services.create_goal(name="Someday", currency="USD", target_minor=1000_00)

        with pytest.raises(services.GoalError, match="Link an account"):
            services.add_contribution(goal=goal, amount_minor=100_00, from_account=checking)

        # And nothing partial was left behind.
        assert finance_selectors.account_current_balance_minor(checking) == 500_00
        assert selectors.goal_status(goal).saved_minor == 0


def test_funding_from_the_destination_itself_is_refused():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        _checking, savings = _accounts()
        goal = services.create_goal(
            name="Circular", currency="USD", target_minor=1000_00, linked_account=savings
        )

        with pytest.raises(services.GoalError):
            services.add_contribution(goal=goal, amount_minor=100_00, from_account=savings)


def test_cross_currency_funding_is_refused_rather_than_transferred_at_par():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        eur_checking = finance_services.create_financial_account(
            name="EUR Checking", account_type=AccountType.CHECKING, currency="EUR"
        )
        finance_services.set_opening_balance(financial_account=eur_checking, amount_minor=500_00)
        usd_savings = finance_services.create_financial_account(
            name="USD Savings", account_type=AccountType.SAVINGS, currency="USD"
        )
        goal = services.create_goal(
            name="Mixed", currency="USD", target_minor=1000_00, linked_account=usd_savings
        )

        with pytest.raises(services.GoalError, match="USD"):
            services.add_contribution(goal=goal, amount_minor=100_00, from_account=eur_checking)


def test_funding_and_an_explicit_source_transaction_are_mutually_exclusive():
    """Both would claim to answer 'where did this come from?' differently."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking, savings = _accounts()
        goal = services.create_goal(
            name="Ambiguous", currency="USD", target_minor=1000_00, linked_account=savings
        )
        txn = finance_services.set_opening_balance(financial_account=savings, amount_minor=1_00)

        with pytest.raises(services.GoalError):
            services.add_contribution(
                goal=goal,
                amount_minor=100_00,
                from_account=checking,
                source_transaction=txn,
            )


def test_a_funded_contribution_can_complete_a_goal():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking, savings = _accounts()
        goal = services.create_goal(
            name="Almost", currency="USD", target_minor=100_00, linked_account=savings
        )

        services.add_contribution(goal=goal, amount_minor=100_00, from_account=checking)

        goal.refresh_from_db()
        assert goal.status == "achieved"


# --------------------------------------------------------------------- API
def _create_account(client, name, account_type, currency="USD", opening_minor=0):
    res = client.post(
        "/api/v1/finance/accounts/",
        {
            "name": name,
            "account_type": account_type,
            "currency": currency,
            "opening_balance_minor": opening_minor,
        },
        format="json",
    )
    assert res.status_code == 201, res.data
    return res.data["id"]


def test_api_funding_a_contribution_moves_money_and_reports_it(tenant_context):
    _, client = tenant_context
    checking = _create_account(client, "Checking", "checking", opening_minor=500_00)
    savings = _create_account(client, "Savings", "savings")

    goal = client.post(
        "/api/v1/goals/goals/",
        {
            "name": "Emergency fund",
            "currency": "USD",
            "target_minor": 1000_00,
            "linked_account_id": savings,
        },
        format="json",
    )
    assert goal.status_code == 201, goal.data

    contrib = client.post(
        f"/api/v1/goals/goals/{goal.data['id']}/contributions/",
        {"amount_minor": 150_00, "from_account_id": checking},
        format="json",
    )
    assert contrib.status_code == 201, contrib.data
    assert contrib.data["funded"] is True
    assert contrib.data["goal"]["saved_minor"] == 150_00

    accounts = {a["id"]: a for a in client.get("/api/v1/finance/accounts/").data}
    assert accounts[checking]["balance_minor"] == 350_00
    assert accounts[savings]["balance_minor"] == 150_00


def test_api_an_unfunded_contribution_reports_itself_as_unfunded(tenant_context):
    _, client = tenant_context
    checking = _create_account(client, "Checking", "checking", opening_minor=500_00)
    goal = client.post(
        "/api/v1/goals/goals/",
        {"name": "Trip", "currency": "USD", "target_minor": 1000_00},
        format="json",
    )
    contrib = client.post(
        f"/api/v1/goals/goals/{goal.data['id']}/contributions/",
        {"amount_minor": 100_00},
        format="json",
    )
    assert contrib.status_code == 201, contrib.data
    assert contrib.data["funded"] is False

    accounts = {a["id"]: a for a in client.get("/api/v1/finance/accounts/").data}
    assert accounts[checking]["balance_minor"] == 500_00


def test_api_funding_from_another_workspaces_account_is_not_found(tenant_context):
    """A foreign account id must never reach across the tenant boundary."""
    from tests.conftest import _bearer_client
    from tests.factories import MembershipFactory

    _, client = tenant_context
    other = MembershipFactory()
    other_client = _bearer_client(other.user, tenant_id=other.tenant_id)
    foreign_account = _create_account(other_client, "Theirs", "checking")

    goal = client.post(
        "/api/v1/goals/goals/",
        {"name": "Mine", "currency": "USD", "target_minor": 1000_00},
        format="json",
    )
    res = client.post(
        f"/api/v1/goals/goals/{goal.data['id']}/contributions/",
        {"amount_minor": 100_00, "from_account_id": foreign_account},
        format="json",
    )
    assert res.status_code == 404
