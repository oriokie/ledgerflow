"""The projection engine and the life-event compiler.

No database here either — the engine is pure by design, and these tests are
what keep it that way. What they defend:

* the arithmetic identities (net worth reconciles, debts amortise to zero),
* the honesty rules (expenses inflate independently of income, the trough is
  reported rather than averaged away),
* and the compiler contract — that fifteen life events reduce to six
  primitives without the engine growing a branch per decision.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.projections import events as ev
from apps.projections.engine import (
    CompiledEvent,
    DebtPosition,
    EconomicAssumptions,
    FinancialPosition,
    add_months,
    project,
)

TODAY = date(2026, 1, 31)

FLAT = EconomicAssumptions(
    annual_inflation=0.0,
    annual_salary_growth=0.0,
    annual_investment_return=0.0,
    annual_cash_return=0.0,
    effective_tax_rate=0.0,
    annual_property_growth=0.0,
)


def position(**kwargs) -> FinancialPosition:
    base = {
        "currency": "KES",
        "as_of": TODAY,
        "liquid_minor": 1_000_000,
        "monthly_net_income_minor": 500_000,
        "monthly_expenses_minor": 400_000,
    }
    base.update(kwargs)
    return FinancialPosition(**base)


# ---------------------------------------------------------------------------
# month arithmetic
# ---------------------------------------------------------------------------


def test_month_arithmetic_clamps_to_short_months():
    """31 January plus one month is 28 February. Getting this wrong shifts
    every later event by a day and makes two runs disagree."""
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 1, 31), 3) == date(2026, 4, 30)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)  # leap year


def test_month_arithmetic_crosses_years():
    assert add_months(date(2026, 11, 15), 14) == date(2028, 1, 15)


# ---------------------------------------------------------------------------
# the flat case — arithmetic identities
# ---------------------------------------------------------------------------


def test_flat_projection_is_pure_surplus_accumulation():
    result = project(position=position(), assumptions=FLAT, months=12)
    assert len(result.points) == 12
    # 100,000 surplus a month, twelve months, on top of a million.
    assert result.points[-1].liquid_minor == 1_000_000 + 100_000 * 12


def test_net_worth_reconciles_with_its_components_every_month():
    """The identity that catches a whole class of bookkeeping bug."""
    result = project(
        position=position(investment_minor=500_000, other_assets_minor=2_000_000),
        assumptions=FLAT,
        months=24,
    )
    for point in result.points:
        assert point.net_worth_minor == (
            point.liquid_minor + point.investment_minor + point.other_assets_minor - point.debt_balance_minor
        )


def test_projection_is_deterministic():
    """Same inputs, same outputs — the property that makes a saved scenario
    meaningful and two runs comparable."""
    a = project(position=position(), assumptions=FLAT, months=36)
    b = project(position=position(), assumptions=FLAT, months=36)
    assert [p.net_worth_minor for p in a.points] == [p.net_worth_minor for p in b.points]


def test_horizon_ceiling_and_floor_are_enforced():
    with pytest.raises(ValueError, match="at least one month"):
        project(position=position(), months=0)
    with pytest.raises(ValueError, match="ceiling"):
        project(position=position(), months=481)


def test_forty_year_horizon_runs():
    result = project(position=position(), assumptions=FLAT, months=480)
    assert len(result.points) == 480
    assert result.points[-1].on.year == TODAY.year + 40


# ---------------------------------------------------------------------------
# the honesty rules
# ---------------------------------------------------------------------------


def test_expenses_inflate_even_when_income_does_not():
    """The rule that stops every projection flattering itself: prices rise
    whether or not you get a raise."""
    assumptions = EconomicAssumptions(
        annual_inflation=0.10,
        annual_salary_growth=0.0,
        annual_investment_return=0.0,
        annual_cash_return=0.0,
        annual_property_growth=0.0,
    )
    result = project(position=position(), assumptions=assumptions, months=24)
    first, last = result.points[0], result.points[-1]
    assert last.expenses_minor > first.expenses_minor
    assert last.income_minor == first.income_minor


def test_the_trough_is_reported_not_averaged_away():
    """A one-off purchase that dips the balance mid-window must show up as a
    trough even though the closing balance recovers."""
    spend = CompiledEvent(label="Wedding", start_month=3, one_off_cash_minor=-1_500_000)
    result = project(position=position(), assumptions=FLAT, events=[spend], months=24)
    assert result.lowest_liquid_minor < 0
    assert result.lowest_liquid_month == 3
    assert result.first_negative_month == 3
    assert result.first_negative_on == add_months(TODAY, 3)
    # ...and it recovers, which is exactly why the trough had to be reported.
    assert result.points[-1].liquid_minor > 0


def test_a_projection_that_never_goes_negative_says_so():
    result = project(position=position(), assumptions=FLAT, months=24)
    assert result.first_negative_month is None
    assert result.first_negative_on is None


def test_assumptions_travel_with_the_result():
    result = project(position=position(), assumptions=FLAT, months=12)
    assert result.assumptions
    assert any("Inflation" in a for a in result.assumptions)


def test_no_income_is_warned_about():
    result = project(position=position(monthly_net_income_minor=0), assumptions=FLAT, months=12)
    assert any("No recurring income" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# debt
# ---------------------------------------------------------------------------


def test_debt_amortises_to_zero_and_reports_the_month():
    debt = DebtPosition(
        label="Car loan", balance_minor=1_000_000, annual_rate=0.0, monthly_payment_minor=100_000
    )
    result = project(position=position(debts=(debt,)), assumptions=FLAT, months=24)
    assert result.debt_free_month == 10
    assert result.points[-1].debt_balance_minor == 0


def test_debt_interest_is_accumulated_and_reported():
    debt = DebtPosition(
        label="Loan", balance_minor=1_000_000, annual_rate=0.12, monthly_payment_minor=100_000
    )
    result = project(position=position(debts=(debt,)), assumptions=FLAT, months=24)
    assert result.total_interest_paid_minor > 0


def test_a_payment_that_never_touches_principal_is_warned_about():
    """Silently projecting a debt that never moves is worse than saying so."""
    debt = DebtPosition(label="Card", balance_minor=1_000_000, annual_rate=0.24, monthly_payment_minor=15_000)
    result = project(position=position(debts=(debt,)), assumptions=FLAT, months=12)
    assert any("do not cover its interest" in w for w in result.warnings)
    assert result.debt_free_month is None


def test_debt_free_month_is_none_when_there_was_never_any_debt():
    result = project(position=position(), assumptions=FLAT, months=12)
    assert result.debt_free_month is None


# ---------------------------------------------------------------------------
# assets with their own growth rates
# ---------------------------------------------------------------------------


def test_a_vehicle_depreciates_while_a_house_appreciates():
    """One growth rate for all assets would let a car quietly inflate net worth
    for forty years."""
    assumptions = EconomicAssumptions(
        annual_inflation=0.0,
        annual_salary_growth=0.0,
        annual_investment_return=0.0,
        annual_cash_return=0.0,
        annual_property_growth=0.10,
    )
    house = CompiledEvent(label="House", start_month=1, asset_delta_minor=10_000_000)
    car = CompiledEvent(label="Car", start_month=1, asset_delta_minor=10_000_000, asset_annual_growth=-0.15)
    house_only = project(position=position(), assumptions=assumptions, events=[house], months=36)
    car_only = project(position=position(), assumptions=assumptions, events=[car], months=36)
    assert house_only.points[-1].other_assets_minor > 10_000_000
    assert car_only.points[-1].other_assets_minor < 10_000_000


# ---------------------------------------------------------------------------
# recurring events and windows
# ---------------------------------------------------------------------------


def test_a_recurring_event_applies_only_inside_its_window():
    childcare = CompiledEvent(
        label="Childcare", start_month=3, end_month=5, monthly_expense_delta_minor=100_000
    )
    result = project(position=position(), assumptions=FLAT, events=[childcare], months=8)
    by_month = {p.month: p.expenses_minor for p in result.points}
    assert by_month[2] == 400_000
    assert by_month[3] == 500_000
    assert by_month[5] == 500_000
    assert by_month[6] == 400_000


def test_events_are_named_on_the_month_they_fire():
    """So a chart can annotate the point where the line bends."""
    event = CompiledEvent(label="Deposit paid", start_month=4, one_off_cash_minor=-100_000)
    result = project(position=position(), assumptions=FLAT, events=[event], months=6)
    assert result.points[3].events == ("Deposit paid",)
    assert result.points[2].events == ()


def test_clearing_a_debt_costs_the_cash_it_takes_to_clear_it():
    debt = DebtPosition(label="Card", balance_minor=300_000, annual_rate=0.0, monthly_payment_minor=10_000)
    payoff = CompiledEvent(label="Clear card", start_month=2, clears_debt_labels=("Card",))
    result = project(position=position(debts=(debt,)), assumptions=FLAT, events=[payoff], months=6)
    assert result.points[-1].debt_balance_minor == 0
    # The month it cleared, cash fell by the outstanding balance.
    assert result.points[1].liquid_minor < result.points[0].liquid_minor


# ---------------------------------------------------------------------------
# the event compiler
# ---------------------------------------------------------------------------


def test_every_declared_event_kind_has_a_compiler_and_a_label():
    """The registry, the label table and the parameter schema must agree, or a
    kind exists that the API will offer and the engine cannot run."""
    for kind in ev.EventKind.all():
        assert kind in ev.EVENT_PARAMS, f"{kind} has no parameter schema"
        assert kind in ev.EVENT_LABELS, f"{kind} has no label"
        assert kind in ev._COMPILERS, f"{kind} has no compiler"


def test_all_fifteen_life_events_compile_and_run():
    """The product promises fifteen. This is the test that says so."""
    samples = {
        ev.EventKind.HOME_PURCHASE: {"price_minor": 10_000_000, "deposit_minor": 2_000_000},
        ev.EventKind.MORTGAGE: {"principal_minor": 5_000_000, "annual_rate": 0.09},
        ev.EventKind.VEHICLE_PURCHASE: {"price_minor": 2_000_000, "deposit_minor": 500_000},
        ev.EventKind.JOB_CHANGE: {"monthly_gross_delta_minor": 100_000},
        ev.EventKind.SALARY_INCREASE: {"monthly_gross_increase_minor": 50_000},
        ev.EventKind.JOB_LOSS: {"months_without_work": 6},
        ev.EventKind.HOURS_REDUCTION: {"retained_fraction": 0.8},
        ev.EventKind.DEBT_PAYOFF: {"amount_minor": 200_000},
        ev.EventKind.INVEST_MORE: {"monthly_amount_minor": 25_000},
        ev.EventKind.NEW_CHILD: {"monthly_cost_minor": 60_000},
        ev.EventKind.RETIREMENT: {"monthly_pension_income_minor": 200_000},
        ev.EventKind.EDUCATION: {"monthly_cost_minor": 80_000, "duration_months": 24},
        ev.EventKind.RELOCATION: {"moving_cost_minor": 300_000},
        ev.EventKind.BUSINESS_START: {"startup_cost_minor": 1_000_000},
        ev.EventKind.ONE_TIME_PURCHASE: {"amount_minor": 400_000},
    }
    # The two sample maps must jointly cover every declared kind: a kind the
    # API offers and no test exercises is a feature nobody has run.
    assert set(samples) | set(HOUSEHOLD_SAMPLES) == set(
        ev.EventKind.all()
    ), "a life event is missing from these tests"

    pos = position()
    for kind, params in samples.items():
        compiled = ev.compile_event(kind=kind, start_month=2, params=params, position=pos, assumptions=FLAT)
        assert compiled, f"{kind} compiled to nothing"
        result = project(position=pos, assumptions=FLAT, events=compiled, months=60)
        assert len(result.points) == 60


def test_unknown_parameters_are_rejected_rather_than_ignored():
    """A typo that silently does nothing produces a projection which looks like
    it modelled something it did not."""
    with pytest.raises(ev.EventParamError, match="unknown parameter"):
        ev.validate_params(ev.EventKind.SALARY_INCREASE, {"monthly_gros_increase_minor": 1})


def test_missing_required_parameters_are_rejected():
    with pytest.raises(ev.EventParamError, match="required"):
        ev.validate_params(ev.EventKind.HOME_PURCHASE, {})


def test_unknown_event_kind_is_rejected():
    with pytest.raises(ev.EventParamError, match="unknown event kind"):
        ev.validate_params("winning_the_lottery", {})


def test_gross_income_is_converted_to_net_exactly_once():
    taxed = EconomicAssumptions(effective_tax_rate=0.30)
    compiled = ev.compile_event(
        kind=ev.EventKind.SALARY_INCREASE,
        start_month=1,
        params={"monthly_gross_increase_minor": 100_000},
        position=position(),
        assumptions=taxed,
    )
    assert compiled[0].monthly_income_delta_minor == 70_000


def test_job_loss_is_proportional_to_what_the_job_actually_pays():
    """The user should not have to restate income the app already knows."""
    compiled = ev.compile_event(
        kind=ev.EventKind.JOB_LOSS,
        start_month=1,
        params={"months_without_work": 3},
        position=position(monthly_net_income_minor=500_000),
        assumptions=FLAT,
    )
    loss = next(c for c in compiled if c.monthly_income_delta_minor)
    assert loss.monthly_income_delta_minor == -500_000
    assert loss.end_month == 3


def test_job_loss_with_replacement_income_only_loses_the_difference():
    compiled = ev.compile_event(
        kind=ev.EventKind.JOB_LOSS,
        start_month=1,
        params={"months_without_work": 3, "monthly_replacement_income_minor": 200_000},
        position=position(monthly_net_income_minor=500_000),
        assumptions=FLAT,
    )
    loss = next(c for c in compiled if c.monthly_income_delta_minor)
    assert loss.monthly_income_delta_minor == -300_000


def test_a_home_purchase_compiles_to_deposit_asset_debt_and_running_costs():
    """The clearest statement of the compiler's job: one life event, four
    primitives, no engine special-casing."""
    compiled = ev.compile_event(
        kind=ev.EventKind.HOME_PURCHASE,
        start_month=6,
        params={
            "price_minor": 10_000_000,
            "deposit_minor": 2_000_000,
            "annual_rate": 0.09,
            "term_years": 25,
            "monthly_running_costs_minor": 30_000,
        },
        position=position(),
        assumptions=FLAT,
    )
    (event,) = compiled
    assert event.one_off_cash_minor == -2_000_000
    assert event.asset_delta_minor == 10_000_000
    assert event.new_debt.balance_minor == 8_000_000
    assert event.monthly_expense_delta_minor == 30_000
    assert event.start_month == 6


def test_a_cash_home_purchase_takes_on_no_debt():
    compiled = ev.compile_event(
        kind=ev.EventKind.HOME_PURCHASE,
        start_month=1,
        params={"price_minor": 5_000_000, "deposit_minor": 5_000_000},
        position=position(),
        assumptions=FLAT,
    )
    assert compiled[0].new_debt is None


def test_business_revenue_only_arrives_after_the_ramp():
    """Modelling revenue from day one is the most flattering thing a business
    projection can do, and the most common reason one is wrong."""
    compiled = ev.compile_event(
        kind=ev.EventKind.BUSINESS_START,
        start_month=1,
        params={
            "startup_cost_minor": 1_000_000,
            "monthly_cost_minor": 50_000,
            "monthly_revenue_minor": 200_000,
            "ramp_months": 9,
        },
        position=position(),
        assumptions=FLAT,
    )
    revenue = next(c for c in compiled if c.monthly_income_delta_minor > 0)
    assert revenue.start_month == 10


def test_retirement_replaces_income_rather_than_adding_to_it():
    compiled = ev.compile_event(
        kind=ev.EventKind.RETIREMENT,
        start_month=1,
        params={"monthly_pension_income_minor": 200_000, "monthly_drawdown_minor": 50_000},
        position=position(monthly_net_income_minor=500_000),
        assumptions=FLAT,
    )
    (event,) = compiled
    assert event.monthly_income_delta_minor == -300_000
    assert event.monthly_investment_delta_minor == -50_000


def test_hours_reduction_must_retain_a_sensible_fraction():
    with pytest.raises(ev.EventParamError, match="retained_fraction"):
        ev.compile_event(
            kind=ev.EventKind.HOURS_REDUCTION,
            start_month=1,
            params={"retained_fraction": 1.5},
            position=position(),
            assumptions=FLAT,
        )


def test_start_month_is_one_based():
    with pytest.raises(ev.EventParamError, match="1-based"):
        ev.compile_event(
            kind=ev.EventKind.INVEST_MORE,
            start_month=0,
            params={"monthly_amount_minor": 1},
            position=position(),
            assumptions=FLAT,
        )


# ---------------------------------------------------------------------------
# household life events (Phase 3)
# ---------------------------------------------------------------------------


#: The Phase 3 additions, kept at module level so the completeness assertion
#: above can prove the two maps jointly cover every declared kind.
HOUSEHOLD_SAMPLES = {
    ev.EventKind.MARRIAGE: {
        "wedding_cost_minor": 800_000,
        "partner_monthly_gross_income_minor": 300_000,
    },
    ev.EventKind.PARENTAL_LEAVE: {"months": 9, "paid_fraction": 0.4},
    ev.EventKind.SEPARATION: {"retained_income_fraction": 0.6},
    ev.EventKind.CARING_FOR_PARENT: {"monthly_cost_minor": 80_000, "years": 4},
    ev.EventKind.INHERITANCE: {"amount_minor": 5_000_000, "invested_fraction": 0.8},
}


def test_all_five_household_events_compile_and_run():
    """Phase 3 adds five life events and no engine branches — the compiler
    absorbs them, which is the whole reason it exists."""
    pos = position()
    for kind, params in HOUSEHOLD_SAMPLES.items():
        compiled = ev.compile_event(kind=kind, start_month=2, params=params, position=pos, assumptions=FLAT)
        assert compiled, f"{kind} compiled to nothing"
        result = project(position=pos, assumptions=FLAT, events=compiled, months=120)
        assert len(result.points) == 120


def test_parental_leave_defaults_to_unpaid_which_is_the_pessimistic_reading():
    """Entitlement varies enormously; a projection that assumes generous cover
    is the one that surprises people at the worst possible moment."""
    compiled = ev.compile_event(
        kind=ev.EventKind.PARENTAL_LEAVE,
        start_month=1,
        params={"months": 6},
        position=position(monthly_net_income_minor=500_000),
        assumptions=FLAT,
    )
    (event,) = compiled
    assert event.monthly_income_delta_minor == -500_000
    assert event.end_month == 6


def test_paid_leave_only_loses_the_unpaid_share():
    compiled = ev.compile_event(
        kind=ev.EventKind.PARENTAL_LEAVE,
        start_month=1,
        params={"months": 6, "paid_fraction": 0.6},
        position=position(monthly_net_income_minor=500_000),
        assumptions=FLAT,
    )
    assert compiled[0].monthly_income_delta_minor == -200_000


def test_marriage_adds_the_partners_income_net_of_tax():
    taxed = EconomicAssumptions(effective_tax_rate=0.25)
    compiled = ev.compile_event(
        kind=ev.EventKind.MARRIAGE,
        start_month=1,
        params={"partner_monthly_gross_income_minor": 400_000},
        position=position(),
        assumptions=taxed,
    )
    assert compiled[0].monthly_income_delta_minor == 300_000


def test_separation_splits_assets_and_income():
    compiled = ev.compile_event(
        kind=ev.EventKind.SEPARATION,
        start_month=1,
        params={"retained_income_fraction": 0.5, "retained_assets_fraction": 0.5},
        position=position(liquid_minor=2_000_000, monthly_net_income_minor=500_000),
        assumptions=FLAT,
    )
    (event,) = compiled
    assert event.monthly_income_delta_minor == -250_000
    assert event.one_off_cash_minor == -1_000_000


def test_caring_for_a_parent_costs_money_and_sometimes_earnings():
    compiled = ev.compile_event(
        kind=ev.EventKind.CARING_FOR_PARENT,
        start_month=1,
        params={"monthly_cost_minor": 50_000, "years": 3, "income_reduction_fraction": 0.2},
        position=position(monthly_net_income_minor=500_000),
        assumptions=FLAT,
    )
    (event,) = compiled
    assert event.monthly_expense_delta_minor == 50_000
    assert event.monthly_income_delta_minor == -100_000
    assert event.end_month == 36


def test_an_inheritance_splits_between_cash_and_invested():
    compiled = ev.compile_event(
        kind=ev.EventKind.INHERITANCE,
        start_month=1,
        params={"amount_minor": 1_000_000, "invested_fraction": 0.75},
        position=position(),
        assumptions=FLAT,
    )
    cash = next(c for c in compiled if c.one_off_cash_minor)
    invested = next(c for c in compiled if c.asset_delta_minor)
    assert cash.one_off_cash_minor == 250_000
    assert invested.asset_delta_minor == 750_000


def test_an_inheritance_is_taken_as_received_with_no_tax_guessed():
    """Inheritance tax varies by jurisdiction, relationship and estate
    structure to a degree this product cannot responsibly guess at."""
    compiled = ev.compile_event(
        kind=ev.EventKind.INHERITANCE,
        start_month=1,
        params={"amount_minor": 1_000_000, "invested_fraction": 0.0},
        position=position(),
        assumptions=EconomicAssumptions(effective_tax_rate=0.4),
    )
    assert compiled[0].one_off_cash_minor == 1_000_000
