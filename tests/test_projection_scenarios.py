"""Saved scenarios: persistence, lifecycle, and binding to the engine.

Where `test_projection_engine` proves the arithmetic, this proves the parts
that touch the database — and the properties that only mean anything once a
scenario is a row someone else could read:

* a scenario writes nothing financial, ever,
* duplicating one copies its events but not its status,
* comparison snapshots the position once,
* and the tables are behind row-level security like everything else.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind
from apps.ledger.models import JournalEntry
from apps.projections import adapters, services
from apps.projections.events import EventKind
from apps.projections.models import (
    AssumptionSet,
    Scenario,
    ScenarioEvent,
    ScenarioStatus,
    ScenarioVisibility,
)
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _month_back(n: int) -> date:
    today = timezone.localdate()
    month, year = today.month - n, today.year
    while month <= 0:
        month, year = month + 12, year - 1
    return date(year, month, 15)


def _seed(income=500_000, spend=300_000, opening=1_000_000):
    """Six complete months of history, so the adapter has something to measure."""
    account = finance_services.create_financial_account(
        name="Checking",
        account_type=AccountType.CHECKING,
        currency="USD",
        opening_balance_minor=opening,
    )
    salary = finance_services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
    groceries = finance_services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
    for n in range(1, 7):
        when = _month_back(n)
        at = datetime(when.year, when.month, when.day, 12, tzinfo=UTC)
        finance_services.record_income(
            financial_account=account, category=salary, amount_minor=income, occurred_at=at
        )
        finance_services.record_expense(
            financial_account=account, category=groceries, amount_minor=spend, occurred_at=at
        )
    return account


# ---------------------------------------------------------------------------
# the position adapter
# ---------------------------------------------------------------------------


def test_the_position_is_measured_from_the_ledger_not_asked_for(tenant):
    with tenant_scope(tenant):
        _seed()
        position = adapters.current_position()

    assert position.currency == "USD"
    assert position.monthly_net_income_minor == 500_000
    assert position.monthly_expenses_minor == 300_000
    assert position.liquid_minor > 0


def test_recurring_income_floors_the_projection_when_history_has_not_caught_up(tenant):
    """A salary entered as a schedule last week has not reached the trailing
    median yet. The projection must still use it — that is the whole point of
    capturing recurring income."""
    from apps.finance import recurring as recurring_service
    from apps.finance.models import RecurringType

    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=1_000_000,
        )
        salary = finance_services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
        recurring_service.create_recurring_transaction(
            txn_type=RecurringType.INCOME,
            financial_account=account,
            category=salary,
            amount_minor=400_000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 1, 1),
        )
        position = adapters.current_position(as_of=date(2026, 8, 13))

    assert position.monthly_net_income_minor == 400_000


def test_a_schedule_end_date_drops_the_amount_from_later_months(tenant):
    """A contract that ends in October must not be projected as a forty-year
    salary. Month 1–2 still have it; November does not."""
    from apps.finance import recurring as recurring_service
    from apps.finance.models import RecurringType
    from apps.projections.engine import EconomicAssumptions

    flat = EconomicAssumptions(
        annual_inflation=0.0,
        annual_salary_growth=0.0,
        annual_investment_return=0.0,
        annual_cash_return=0.0,
        annual_property_growth=0.0,
    )
    as_of = date(2026, 8, 13)
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=1_000_000,
        )
        salary = finance_services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
        recurring_service.create_recurring_transaction(
            txn_type=RecurringType.INCOME,
            financial_account=account,
            category=salary,
            amount_minor=400_000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 10, 31),
        )
        position = adapters.current_position(as_of=as_of)
        result = adapters.project_live(position=position, assumptions=flat, months=6)

    assert position.monthly_net_income_minor == 400_000
    assert result.points[0].income_minor == 400_000  # September
    assert result.points[1].income_minor == 400_000  # October
    assert result.points[2].income_minor == 0  # November, past ends_on


def test_the_cashflow_stack_names_measured_income_and_spend(tenant):
    with tenant_scope(tenant):
        _seed()
        stack = adapters.cashflow_stack(currency="USD", as_of=timezone.localdate())

    labels = {line["label"] for line in stack}
    assert "Salary" in labels or any(line["direction"] == "in" for line in stack)
    assert any(line["direction"] == "out" for line in stack)
    assert all(line["monthly_minor"] > 0 for line in stack)


def test_unlinked_recurring_income_is_named_on_the_stack_alongside_a_source(tenant):
    """A salary captured as an income source must not hide a second paycheck
    that only exists as a Recurring INCOME template."""
    from apps.finance import recurring as recurring_service
    from apps.finance.models import RecurringType
    from apps.income import services as income_services
    from apps.income.models import IncomeKind, Reliability

    as_of = date(2026, 8, 13)
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=1_000_000,
        )
        salary = finance_services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
        income_services.create_source(
            name="Day job",
            kind=IncomeKind.EMPLOYMENT,
            currency="USD",
            net_minor=300_000,
            frequency="monthly",
            reliability=Reliability.FIXED,
            starts_on=date(2026, 1, 1),
        )
        recurring_service.create_recurring_transaction(
            txn_type=RecurringType.INCOME,
            financial_account=account,
            category=salary,
            amount_minor=150_000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 1, 1),
            memo="Side gig",
        )
        stack = adapters.cashflow_stack(currency="USD", as_of=as_of)
        position = adapters.current_position(as_of=as_of)

    incoming = [line for line in stack if line["direction"] == "in" and line["kind"] != "residual"]
    labels = {line["label"] for line in incoming}
    assert "Day job" in labels
    assert "Side gig" in labels
    assert position.monthly_net_income_minor >= 450_000


def test_recurring_expense_is_named_going_out(tenant):
    """Rent captured under Recurring must appear as a named Going-out line,
    not only as anonymous residual spending."""
    from apps.finance import recurring as recurring_service
    from apps.finance.models import RecurringType

    as_of = date(2026, 8, 13)
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=1_000_000,
        )
        rent = finance_services.create_category(name="Rent", kind=CategoryKind.EXPENSE, currency="USD")
        recurring_service.create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            category=rent,
            amount_minor=80_000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 1, 1),
            memo="Rent",
        )
        stack = adapters.cashflow_stack(currency="USD", as_of=as_of)
        position = adapters.current_position(as_of=as_of)

    outgoing = [line for line in stack if line["direction"] == "out" and line["kind"] == "recurring"]
    assert any(line["label"] == "Rent" and line["monthly_minor"] == 80_000 for line in outgoing)
    assert position.monthly_expenses_minor >= 80_000


def test_a_posted_schedule_still_counts_when_starts_on_was_moved_to_next_due(tenant):
    """Editing used to write next_run_on into starts_on. A rent that has
    already posted must still floor the projection."""
    from apps.finance import recurring as recurring_service
    from apps.finance.models import RecurringTransaction, RecurringType

    as_of = date(2026, 8, 13)
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=1_000_000,
        )
        rent = finance_services.create_category(name="Rent", kind=CategoryKind.EXPENSE, currency="USD")
        rec = recurring_service.create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            category=rent,
            amount_minor=80_000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 1, 1),
            memo="Rent",
        )
        RecurringTransaction.objects.filter(pk=rec.pk).update(
            occurrences_created=7,
            starts_on=date(2026, 9, 1),
            next_run_on=date(2026, 9, 1),
        )
        stack = adapters.cashflow_stack(currency="USD", as_of=as_of)
        position = adapters.current_position(as_of=as_of)

    outgoing = [line for line in stack if line["label"] == "Rent"]
    assert outgoing and outgoing[0]["current"] is True
    assert position.monthly_expenses_minor >= 80_000


def test_an_irregular_linked_source_does_not_hide_the_paycheck_template(tenant):
    """A linked IncomeSource that itself does not count (irregular, no
    receipts) must not take the Recurring INCOME template down with it."""
    from apps.finance import recurring as recurring_service
    from apps.finance.models import RecurringType
    from apps.income import services as income_services
    from apps.income.models import IncomeKind, Reliability

    as_of = date(2026, 8, 13)
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=1_000_000,
        )
        salary = finance_services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
        template = recurring_service.create_recurring_transaction(
            txn_type=RecurringType.INCOME,
            financial_account=account,
            category=salary,
            amount_minor=400_000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 1, 1),
            memo="Paycheck",
        )
        income_services.create_source(
            name="Freelance",
            kind=IncomeKind.SELF_EMPLOYMENT,
            currency="USD",
            net_minor=400_000,
            frequency="monthly",
            reliability=Reliability.IRREGULAR,
            starts_on=date(2026, 1, 1),
            recurring_transaction=template,
        )
        stack = adapters.cashflow_stack(currency="USD", as_of=as_of)
        position = adapters.current_position(as_of=as_of)

    incoming = [line for line in stack if line["direction"] == "in" and line["kind"] != "residual"]
    labels = {line["label"] for line in incoming}
    assert "Paycheck" in labels
    assert "Freelance" not in labels
    assert position.monthly_net_income_minor >= 400_000


def test_a_schedule_that_starts_next_month_is_listed_but_not_in_this_months_rate(tenant):
    from apps.finance import recurring as recurring_service
    from apps.finance.models import RecurringType

    as_of = date(2026, 8, 13)
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=1_000_000,
        )
        rent = finance_services.create_category(name="Rent", kind=CategoryKind.EXPENSE, currency="USD")
        recurring_service.create_recurring_transaction(
            txn_type=RecurringType.EXPENSE,
            financial_account=account,
            category=rent,
            amount_minor=90_000,
            currency="USD",
            frequency="monthly",
            starts_on=date(2026, 10, 1),
            memo="New lease",
        )
        stack = adapters.cashflow_stack(currency="USD", as_of=as_of)
        position = adapters.current_position(as_of=as_of)
        events = adapters.schedule_adjustments(position)

    line = next(line for line in stack if line["label"] == "New lease")
    assert line["current"] is False
    assert line["starts_on"] == "2026-10-01"
    assert position.monthly_expenses_minor == 0
    assert any(event.label == "New lease" and event.start_month == 2 for event in events)


def test_a_real_debts_apr_is_converted_from_percent_to_a_fraction(tenant):
    """The debt context stores APR as a percentage (21.5) and the engine takes
    fractions (0.215). The two conventions meet in the adapter and nowhere else.

    This is a regression test with a scar: passing the percentage straight
    through made every workspace carrying a debt 500 on the projection endpoint,
    and no synthetic-position test could catch it because those build a
    `DebtPosition` by hand and never cross the boundary.
    """
    from decimal import Decimal

    from apps.debt import services as debt_services

    with tenant_scope(tenant):
        _seed()
        card = finance_services.create_financial_account(
            name="Credit card",
            account_type=AccountType.CREDIT_CARD,
            currency="USD",
            # A magnitude: the account type makes it a liability.
            opening_balance_minor=500_000,
        )
        debt_services.set_debt_terms(
            financial_account=card, apr=Decimal("21.5"), minimum_payment_minor=25_000
        )

        position = adapters.current_position()
        debts = [d for d in position.debts if d.label == "Credit card"]
        assert debts, "the card should appear in the projected position"
        assert debts[0].annual_rate == pytest.approx(0.215)

        # ...and the projection runs rather than tripping the rate guard.
        scenario = services.create_scenario(name="With the card", horizon_months=24)
        result = services.run(scenario)
        assert result.baseline.total_interest_paid_minor > 0


def test_an_empty_workspace_is_told_to_add_an_account_not_shown_a_forecast(tenant):
    with tenant_scope(tenant), pytest.raises(adapters.NoPositionError, match="Add a current"):
        adapters.current_position()


def test_the_current_month_is_excluded_from_the_run_rate(tenant):
    """The current month always looks frugal because it has not finished, and
    including it builds optimism into every projection downstream."""
    with tenant_scope(tenant):
        account = _seed()
        salary = finance_services.create_category(name="Bonus", kind=CategoryKind.INCOME, currency="USD")
        # A large inflow *this* month must not move the measured run rate.
        finance_services.record_income(
            financial_account=account,
            category=salary,
            amount_minor=99_000_000,
            occurred_at=timezone.now(),
        )
        position = adapters.current_position()

    assert position.monthly_net_income_minor == 500_000


# ---------------------------------------------------------------------------
# assumption sets
# ---------------------------------------------------------------------------


def test_the_default_assumption_set_is_created_once_and_reused(tenant):
    with tenant_scope(tenant):
        first = services.ensure_default_assumption_set()
        second = services.ensure_default_assumption_set()

    assert first.id == second.id
    assert first.is_default


def test_changing_an_assumption_moves_every_scenario_that_shares_it(tenant):
    """The reason assumptions are a separate model. If the numbers were copied
    onto each scenario, half of them would quietly answer a question nobody is
    asking any more."""
    with tenant_scope(tenant):
        _seed()
        assumptions = services.ensure_default_assumption_set()
        scenario = services.create_scenario(name="Base case", horizon_months=120)

        before = services.run(scenario).baseline.closing_net_worth_minor
        services.update_assumption_set(assumptions, annual_inflation="0.1500")
        scenario.refresh_from_db()
        after = services.run(scenario).baseline.closing_net_worth_minor

    assert after != before


def test_unknown_assumption_fields_are_rejected(tenant):
    with tenant_scope(tenant):
        assumptions = services.ensure_default_assumption_set()
        with pytest.raises(services.ScenarioError, match="unknown assumption"):
            services.update_assumption_set(assumptions, annual_unicorns="1.0")


# ---------------------------------------------------------------------------
# scenario lifecycle
# ---------------------------------------------------------------------------


def test_a_scenario_writes_nothing_to_the_ledger(tenant):
    """The load-bearing promise of the whole feature: modelling losing your job
    must not touch the record of what actually happened."""
    with tenant_scope(tenant):
        _seed()
        before = JournalEntry.objects.count()

        scenario = services.create_scenario(name="Redundancy")
        services.add_event(
            scenario=scenario,
            kind=EventKind.JOB_LOSS,
            params={"months_without_work": 6},
            start_month=2,
        )
        services.run(scenario)

        assert JournalEntry.objects.count() == before


def test_an_event_the_engine_would_refuse_never_reaches_the_database(tenant):
    with tenant_scope(tenant):
        scenario = services.create_scenario(name="Typo")
        with pytest.raises(ValidationError):
            services.add_event(
                scenario=scenario,
                kind=EventKind.SALARY_INCREASE,
                params={"monthly_gros_increase_minor": 100},
            )
        assert ScenarioEvent.objects.filter(scenario=scenario).count() == 0


def test_an_event_outside_the_window_is_rejected(tenant):
    with tenant_scope(tenant):
        scenario = services.create_scenario(name="Too far", horizon_months=12)
        with pytest.raises(services.ScenarioError, match="outside this scenario"):
            services.add_event(
                scenario=scenario,
                kind=EventKind.INVEST_MORE,
                params={"monthly_amount_minor": 1},
                start_month=24,
            )


def test_duplicating_copies_the_events_but_not_the_status(tenant):
    """A duplicate is by definition something being worked on; inheriting
    ACTIVE would quietly add a second 'current plan' to the workspace."""
    with tenant_scope(tenant):
        original = services.create_scenario(name="Buy the house", status=ScenarioStatus.ACTIVE)
        services.add_event(
            scenario=original,
            kind=EventKind.HOME_PURCHASE,
            params={"price_minor": 10_000_000, "deposit_minor": 2_000_000},
            start_month=6,
        )
        copy = services.duplicate_scenario(original)

        assert copy.id != original.id
        assert copy.status == ScenarioStatus.DRAFT
        assert copy.duplicated_from_id == original.id
        assert copy.events.count() == original.events.count() == 1
        assert copy.events.first().params == original.events.first().params


def test_duplicating_twice_does_not_collide_on_the_name(tenant):
    with tenant_scope(tenant):
        original = services.create_scenario(name="Plan")
        first = services.duplicate_scenario(original)
        second = services.duplicate_scenario(original)

    assert first.name != second.name


def test_archiving_keeps_the_scenario_readable(tenant):
    """Archive is not delete — the point is that last year's thinking survives."""
    with tenant_scope(tenant):
        scenario = services.create_scenario(name="Old plan")
        services.archive_scenario(scenario)
        assert Scenario.objects.filter(id=scenario.id).exists()
        assert Scenario.objects.get(id=scenario.id).status == ScenarioStatus.ARCHIVED


def test_scenarios_are_private_by_default(tenant):
    """People model things they are not ready to discuss. A planner that shares
    by default is one people will not tell the truth to."""
    with tenant_scope(tenant):
        scenario = services.create_scenario(name="Thinking about it")
    assert scenario.visibility == ScenarioVisibility.PRIVATE


def test_visibility_can_be_shared_with_the_household(tenant):
    with tenant_scope(tenant):
        scenario = services.create_scenario(name="Shared plan")
        services.set_visibility(scenario, ScenarioVisibility.HOUSEHOLD)
        scenario.refresh_from_db()
    assert scenario.visibility == ScenarioVisibility.HOUSEHOLD


def test_unknown_visibility_is_rejected(tenant):
    with tenant_scope(tenant):
        scenario = services.create_scenario(name="Plan")
        with pytest.raises(services.ScenarioError, match="unknown visibility"):
            services.set_visibility(scenario, "everyone")


# ---------------------------------------------------------------------------
# running and comparing
# ---------------------------------------------------------------------------


def test_a_scenario_with_no_events_reproduces_the_baseline_exactly(tenant):
    """The null-scenario rule, inherited from the existing what-if module: any
    drift means the two legs run different arithmetic."""
    with tenant_scope(tenant):
        _seed()
        scenario = services.create_scenario(name="Nothing changes")
        result = services.run(scenario)

    assert [p.net_worth_minor for p in result.scenario.points] == [
        p.net_worth_minor for p in result.baseline.points
    ]
    assert result.net_worth_delta_minor == 0


def test_a_disabled_event_is_excluded_without_being_deleted(tenant):
    """The 'what if we skipped the car' question, asked without losing the car."""
    with tenant_scope(tenant):
        _seed()
        scenario = services.create_scenario(name="With a car")
        event = services.add_event(
            scenario=scenario,
            kind=EventKind.VEHICLE_PURCHASE,
            params={"price_minor": 2_000_000, "deposit_minor": 2_000_000},
            start_month=2,
        )
        with_car = services.run(scenario).net_worth_delta_minor

        event.is_enabled = False
        event.save()
        without_car = services.run(scenario).net_worth_delta_minor

        assert with_car != 0
        assert without_car == 0
        assert ScenarioEvent.objects.filter(id=event.id).exists()


def test_a_pay_rise_improves_the_closing_position(tenant):
    with tenant_scope(tenant):
        _seed()
        scenario = services.create_scenario(name="Promotion")
        services.add_event(
            scenario=scenario,
            kind=EventKind.SALARY_INCREASE,
            params={"monthly_gross_increase_minor": 100_000},
            start_month=1,
        )
        result = services.run(scenario)

    assert result.net_worth_delta_minor > 0


def test_a_child_lowers_the_trough(tenant):
    with tenant_scope(tenant):
        _seed()
        scenario = services.create_scenario(name="Baby")
        services.add_event(
            scenario=scenario,
            kind=EventKind.NEW_CHILD,
            params={"monthly_cost_minor": 200_000, "one_off_cost_minor": 500_000},
            start_month=3,
        )
        result = services.run(scenario)

    assert result.trough_delta_minor < 0


def test_comparison_snapshots_the_position_once(tenant):
    """Re-reading the position per scenario would let a balance change
    mid-comparison and produce a ranking that reflects timing, not decisions."""
    with tenant_scope(tenant):
        _seed()
        a = services.create_scenario(name="Option A")
        services.add_event(
            scenario=a,
            kind=EventKind.SALARY_INCREASE,
            params={"monthly_gross_increase_minor": 50_000},
        )
        b = services.create_scenario(name="Option B")
        services.add_event(
            scenario=b,
            kind=EventKind.SALARY_INCREASE,
            params={"monthly_gross_increase_minor": 100_000},
        )
        comparison = services.compare([a, b])

    assert len(comparison.runs) == 2
    # Same snapshot means identical baselines.
    assert (
        comparison.runs[0].baseline.closing_net_worth_minor
        == comparison.runs[1].baseline.closing_net_worth_minor
    )
    assert comparison.runs[1].net_worth_delta_minor > comparison.runs[0].net_worth_delta_minor


def test_comparing_scenarios_with_different_assumptions_says_so(tenant):
    """Otherwise part of the difference is a disagreement about inflation
    rather than about the plan, and nothing on screen would say which."""
    with tenant_scope(tenant):
        _seed()
        optimistic = AssumptionSet.objects.create(name="Optimistic", annual_investment_return="0.1200")
        a = services.create_scenario(name="A")
        b = services.create_scenario(name="B", assumption_set=optimistic)
        comparison = services.compare([a, b])

    assert any("difference of opinion" in note for note in comparison.notes)


def test_comparing_nothing_is_an_error(tenant):
    with tenant_scope(tenant), pytest.raises(services.ScenarioError, match="nothing to compare"):
        services.compare([])


def test_the_run_carries_its_assumptions_and_notes(tenant):
    with tenant_scope(tenant):
        _seed()
        scenario = services.create_scenario(name="Plan")
        result = services.run(scenario)

    assert result.baseline.assumptions
    assert any("same arithmetic" in note for note in result.notes)


# ---------------------------------------------------------------------------
# tenant isolation
# ---------------------------------------------------------------------------


def test_scenarios_do_not_leak_across_tenants(tenant):
    other = uuid.uuid4()
    with tenant_scope(tenant):
        services.create_scenario(name="Mine")

    with tenant_scope(other):
        assert Scenario.objects.count() == 0

    with tenant_scope(tenant):
        assert Scenario.objects.count() == 1


def test_scenario_events_do_not_leak_across_tenants(tenant):
    other = uuid.uuid4()
    with tenant_scope(tenant):
        scenario = services.create_scenario(name="Mine")
        services.add_event(
            scenario=scenario,
            kind=EventKind.INVEST_MORE,
            params={"monthly_amount_minor": 1_000},
        )

    with tenant_scope(other):
        assert ScenarioEvent.objects.count() == 0


def test_assumption_sets_do_not_leak_across_tenants(tenant):
    other = uuid.uuid4()
    with tenant_scope(tenant):
        services.ensure_default_assumption_set()

    with tenant_scope(other):
        assert AssumptionSet.objects.count() == 0
        # ...and the other tenant gets its own rather than inheriting one.
        services.ensure_default_assumption_set()
        assert AssumptionSet.objects.count() == 1
