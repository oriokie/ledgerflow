"""The calculator library — pure arithmetic, so tested as arithmetic.

No database, no tenant, no fixtures. What these tests are really defending is
a short list of invariants that, when they break, break silently and produce
numbers that look plausible:

* a schedule's principal column sums to exactly the principal,
* a loan ends at exactly zero,
* the two compounding conventions stay attached to the right callers,
* the inverse answers agree with the forward ones.

The last is the most valuable: `savings_goal` answers "when will I get there"
and "what would it take", and those two are computed by different code paths.
Round-tripping one through the other is what proves neither has drifted.
"""

from __future__ import annotations

import pytest

from apps.projections import calculators as calc

# ---------------------------------------------------------------------------
# rate conventions
# ---------------------------------------------------------------------------


def test_nominal_and_effective_conventions_differ_and_both_are_right():
    """A 12% loan charges 1% a month. A 12% investment does not — it ends the
    year exactly 12% up, which is less than 1% a month compounded."""
    assert calc.monthly_rate(0.12) == pytest.approx(0.01)
    effective = calc.monthly_rate(0.12, compounding="effective")
    assert effective < 0.01
    assert (1 + effective) ** 12 == pytest.approx(1.12)


def test_rates_given_as_percentages_are_rejected():
    """7 instead of 0.07 is the most common caller error in this domain and it
    produces a plausible-looking catastrophe rather than a crash."""
    with pytest.raises(calc.CalculatorError, match="fractions"):
        calc.monthly_rate(7.0)


def test_unknown_compounding_convention_is_rejected():
    with pytest.raises(calc.CalculatorError, match="compounding"):
        calc.monthly_rate(0.05, compounding="daily")


# ---------------------------------------------------------------------------
# amortisation invariants
# ---------------------------------------------------------------------------


def test_principal_column_sums_to_exactly_the_principal():
    """The invariant that catches rounding drift. Interest is rounded to the
    cent every month for 360 months; without the final-payment adjustment the
    schedule ends a few cents off and the balance never quite reaches zero."""
    result = calc.amortise(principal_minor=25_000_000, annual_rate=0.065, months=360)
    assert sum(p.principal_minor for p in result.schedule) == 25_000_000


def test_balance_reaches_exactly_zero():
    result = calc.amortise(principal_minor=25_000_000, annual_rate=0.065, months=360)
    assert result.schedule[-1].balance_minor == 0


def test_total_paid_is_principal_plus_interest():
    result = calc.amortise(principal_minor=1_200_000, annual_rate=0.09, months=48)
    assert result.total_paid_minor == result.principal_minor + result.total_interest_minor


def test_zero_interest_loan_is_principal_split_evenly():
    """An interest-free instalment plan is a real product, and the general
    annuity formula divides by the rate."""
    result = calc.amortise(principal_minor=1_200_00, annual_rate=0.0, months=12)
    assert result.total_interest_minor == 0
    assert result.total_paid_minor == 1_200_00
    assert result.actual_months == 12


def test_payment_matches_the_standard_annuity_formula():
    """Pinned against a hand-computed figure: 200,000 at 6% over 30 years is
    the textbook 1,199.10 a month."""
    payment = calc.level_payment_minor(20_000_000, 0.06, 360)
    assert payment == pytest.approx(119_910, abs=100)


def test_overpayment_shortens_the_term_and_cuts_interest():
    plain = calc.amortise(principal_minor=25_000_000, annual_rate=0.065, months=360)
    boosted = calc.amortise(
        principal_minor=25_000_000, annual_rate=0.065, months=360, extra_monthly_minor=20_000
    )
    assert boosted.actual_months < plain.actual_months
    assert boosted.total_interest_minor < plain.total_interest_minor
    # Still settles exactly.
    assert sum(p.principal_minor for p in boosted.schedule) == 25_000_000


def test_payment_that_never_covers_interest_is_rejected_not_looped():
    """Only reachable with an explicit payment — a *derived* level payment is
    always larger than the first month's interest, by construction. This is the
    minimum-payment credit card: without the guard the loop runs to the horizon
    cap and returns a schedule that silently means 'never'."""
    # 500,000 minor at 24% accrues 10,000 of interest in month one; 5,000 of
    # payment leaves the balance larger than it started.
    with pytest.raises(calc.CalculatorError, match="forever"):
        calc.amortise(principal_minor=500_000, annual_rate=0.24, months=480, payment_minor=5_000)


def test_explicit_payment_answers_when_an_existing_debt_clears():
    """What the projection engine actually asks of a debt the user already
    holds: not what it should cost, but when it is gone at the current payment."""
    result = calc.amortise(principal_minor=500_000, annual_rate=0.24, months=480, payment_minor=25_000)
    assert result.schedule[-1].balance_minor == 0
    assert sum(p.principal_minor for p in result.schedule) == 500_000
    assert result.actual_months > 12


def test_negative_and_non_integer_amounts_are_rejected():
    with pytest.raises(calc.CalculatorError, match="negative"):
        calc.amortise(principal_minor=-1, annual_rate=0.05, months=12)
    with pytest.raises(calc.CalculatorError, match="minor units"):
        calc.amortise(principal_minor=10.5, annual_rate=0.05, months=12)


def test_term_beyond_the_forty_year_ceiling_is_rejected():
    with pytest.raises(calc.CalculatorError, match="ceiling"):
        calc.amortise(principal_minor=1_000_000, annual_rate=0.05, months=481)


# ---------------------------------------------------------------------------
# mortgage
# ---------------------------------------------------------------------------


def test_mortgage_separates_the_quoted_payment_from_the_cost_of_ownership():
    """The distinction this function exists for. Affordability answered off the
    lender's quote is how people end up house-poor."""
    result = calc.mortgage(
        property_price_minor=30_000_000,
        deposit_minor=6_000_000,
        annual_rate=0.055,
        years=25,
        annual_tax_minor=360_000,
        annual_insurance_minor=120_000,
    )
    assert result.loan_minor == 24_000_000
    assert result.monthly_cost_minor > result.monthly_payment_minor
    assert result.monthly_cost_minor == result.monthly_payment_minor + 30_000 + 10_000


def test_mortgage_loan_to_value_is_reported():
    result = calc.mortgage(
        property_price_minor=30_000_000, deposit_minor=6_000_000, annual_rate=0.055, years=25
    )
    assert result.loan_to_value == pytest.approx(0.8)


def test_mortgage_without_tax_or_insurance_says_so():
    """An assumption the user cannot see is an assumption they will not
    question, and this one makes the number optimistic."""
    result = calc.mortgage(
        property_price_minor=30_000_000, deposit_minor=6_000_000, annual_rate=0.055, years=25
    )
    assert any("higher than this payment" in a for a in result.assumptions)


def test_deposit_larger_than_the_property_is_rejected():
    with pytest.raises(calc.CalculatorError, match="deposit exceeds"):
        calc.mortgage(property_price_minor=1_000_000, deposit_minor=2_000_000, annual_rate=0.05, years=10)


# ---------------------------------------------------------------------------
# loan
# ---------------------------------------------------------------------------


def test_loan_measures_the_overpayment_saving_by_running_both_legs():
    result = calc.loan(principal_minor=5_000_000, annual_rate=0.14, months=60, extra_monthly_minor=50_000)
    assert result.interest_saved_minor > 0
    assert result.months_saved > 0
    assert result.actual_months < 60


def test_loan_without_overpayment_reports_no_saving():
    result = calc.loan(principal_minor=5_000_000, annual_rate=0.14, months=60)
    assert result.interest_saved_minor == 0
    assert result.months_saved == 0
    assert result.actual_months == 60


def test_interest_share_answers_what_the_loan_actually_costs():
    result = calc.loan(principal_minor=5_000_000, annual_rate=0.14, months=60)
    assert 0 < result.amortisation.interest_share < 1


# ---------------------------------------------------------------------------
# investment growth
# ---------------------------------------------------------------------------


def test_growth_separates_contributions_from_returns():
    result = calc.investment_growth(
        initial_minor=1_000_000, monthly_contribution_minor=50_000, annual_return=0.07, months=120
    )
    assert result.total_contributed_minor == 1_000_000 + 50_000 * 120
    assert result.total_growth_minor == result.final_balance_minor - result.total_contributed_minor
    assert result.total_growth_minor > 0


def test_growth_matches_the_closed_form_future_value():
    """Pinned against the annuity-due-free closed form so an iteration bug
    cannot hide behind a plausible-looking number."""
    months, i = 120, (1.07) ** (1 / 12) - 1
    expected = 1_000_000 * (1 + i) ** months + 50_000 * ((1 + i) ** months - 1) / i
    result = calc.investment_growth(
        initial_minor=1_000_000, monthly_contribution_minor=50_000, annual_return=0.07, months=months
    )
    assert result.final_balance_minor == pytest.approx(expected, rel=1e-6)


def test_inflation_produces_a_smaller_todays_money_figure():
    result = calc.investment_growth(
        initial_minor=1_000_000,
        monthly_contribution_minor=50_000,
        annual_return=0.07,
        months=360,
        annual_inflation=0.05,
    )
    assert result.real_final_balance_minor < result.final_balance_minor


def test_zero_return_is_pure_saving():
    result = calc.investment_growth(
        initial_minor=0, monthly_contribution_minor=10_000, annual_return=0.0, months=12
    )
    assert result.final_balance_minor == 120_000
    assert result.total_growth_minor == 0


def test_rising_contributions_beat_flat_ones():
    flat = calc.investment_growth(
        initial_minor=0, monthly_contribution_minor=10_000, annual_return=0.05, months=120
    )
    rising = calc.investment_growth(
        initial_minor=0,
        monthly_contribution_minor=10_000,
        annual_return=0.05,
        months=120,
        contribution_growth=0.03,
    )
    assert rising.final_balance_minor > flat.final_balance_minor


# ---------------------------------------------------------------------------
# savings goal — forward and inverse must agree
# ---------------------------------------------------------------------------


def test_forward_and_inverse_answers_agree():
    """The round-trip that proves the two code paths have not drifted: ask what
    monthly amount reaches the target in 24 months, then ask when that amount
    gets there. It must be 24."""
    inverse = calc.savings_goal(
        target_minor=2_400_000,
        current_minor=0,
        monthly_contribution_minor=0,
        annual_return=0.04,
        by_months=24,
    )
    forward = calc.savings_goal(
        target_minor=2_400_000,
        current_minor=0,
        monthly_contribution_minor=inverse.required_monthly_minor,
        annual_return=0.04,
    )
    assert forward.months_to_target == 24


def test_goal_already_met_reports_zero_months():
    result = calc.savings_goal(target_minor=100_000, current_minor=150_000, monthly_contribution_minor=0)
    assert result.months_to_target == 0


def test_goal_with_no_contribution_and_no_return_is_unreachable():
    result = calc.savings_goal(
        target_minor=100_000, current_minor=0, monthly_contribution_minor=0, annual_return=0.0
    )
    assert result.months_to_target is None
    assert not result.on_track
    assert any("ceiling" in a for a in result.assumptions)


def test_deadline_produces_shortfall_and_required_contribution():
    result = calc.savings_goal(
        target_minor=1_000_000,
        current_minor=0,
        monthly_contribution_minor=10_000,
        by_months=12,
    )
    assert result.shortfall_minor > 0
    assert result.required_monthly_minor > 10_000
    assert not result.on_track


def test_zero_rate_inverse_is_plain_division():
    result = calc.savings_goal(
        target_minor=1_200_000, current_minor=0, monthly_contribution_minor=0, by_months=12
    )
    assert result.required_monthly_minor == 100_000


# ---------------------------------------------------------------------------
# retirement
# ---------------------------------------------------------------------------


def test_retirement_reports_income_not_just_a_pot():
    """A pot is not an answer. What it buys per month is."""
    result = calc.retirement_estimate(
        current_pot_minor=5_000_000,
        monthly_contribution_minor=50_000,
        years_to_retirement=25,
        annual_return=0.07,
        annual_inflation=0.03,
    )
    assert result.sustainable_monthly_income_minor > 0
    assert result.real_pot_at_retirement_minor < result.pot_at_retirement_minor


def test_retirement_shortfall_produces_the_actionable_inverse():
    result = calc.retirement_estimate(
        current_pot_minor=0,
        monthly_contribution_minor=5_000,
        years_to_retirement=20,
        annual_return=0.06,
        annual_inflation=0.03,
        target_monthly_income_minor=300_000,
    )
    assert not result.on_track
    assert result.monthly_shortfall_minor > 0
    assert result.required_extra_monthly_minor > 0


def test_meeting_the_target_reports_on_track_with_no_required_extra():
    result = calc.retirement_estimate(
        current_pot_minor=100_000_000,
        monthly_contribution_minor=100_000,
        years_to_retirement=20,
        annual_return=0.07,
        annual_inflation=0.02,
        target_monthly_income_minor=1_000,
    )
    assert result.on_track
    assert result.required_extra_monthly_minor is None


def test_overdrawing_a_pot_reports_when_it_runs_out():
    """The question the withdrawal rate hides."""
    result = calc.retirement_estimate(
        current_pot_minor=10_000_000,
        monthly_contribution_minor=0,
        years_to_retirement=1,
        annual_return=0.04,
        annual_inflation=0.02,
        target_monthly_income_minor=500_000,
    )
    assert result.depletion_years is not None
    assert result.depletion_years < 40


def test_absurd_withdrawal_rate_is_rejected():
    with pytest.raises(calc.CalculatorError, match="withdrawal rate"):
        calc.retirement_estimate(
            current_pot_minor=1_000_000,
            monthly_contribution_minor=0,
            years_to_retirement=10,
            annual_return=0.05,
            withdrawal_rate=0.5,
        )


# ---------------------------------------------------------------------------
# net worth
# ---------------------------------------------------------------------------


def test_net_worth_counts_debt_paydown_as_wealth_building():
    """Someone clearing an expensive loan is building net worth as fast as
    someone investing. A projection that models only the asset side says the
    opposite and is wrong."""
    result = calc.net_worth_projection(
        assets_minor=0,
        liabilities_minor=1_000_000,
        monthly_saving_minor=0,
        annual_asset_return=0.0,
        monthly_debt_payment_minor=50_000,
        debt_annual_rate=0.0,
        months=24,
    )
    assert result.opening_net_worth_minor == -1_000_000
    assert result.closing_net_worth_minor == 0
    assert result.breakeven_month == 20


def test_net_worth_breakeven_is_none_when_starting_positive():
    result = calc.net_worth_projection(
        assets_minor=1_000_000,
        liabilities_minor=0,
        monthly_saving_minor=10_000,
        annual_asset_return=0.05,
        monthly_debt_payment_minor=0,
        debt_annual_rate=0.0,
        months=12,
    )
    assert result.breakeven_month is None
    assert result.closing_net_worth_minor > result.opening_net_worth_minor


def test_net_worth_projection_emits_a_point_per_month():
    result = calc.net_worth_projection(
        assets_minor=100_000,
        liabilities_minor=0,
        monthly_saving_minor=1_000,
        annual_asset_return=0.03,
        monthly_debt_payment_minor=0,
        debt_annual_rate=0.0,
        months=36,
    )
    assert len(result.points) == 36
    assert result.points[-1].month == 36


# ---------------------------------------------------------------------------
# every calculator states its assumptions
# ---------------------------------------------------------------------------


def test_every_calculator_returns_its_assumptions():
    """A number without its assumptions is not decision support, and the
    product's stated standard is that every figure carries them."""
    results = [
        calc.mortgage(property_price_minor=1_000_000, deposit_minor=100_000, annual_rate=0.05, years=10),
        calc.loan(principal_minor=1_000_000, annual_rate=0.1, months=24),
        calc.investment_growth(
            initial_minor=1_000, monthly_contribution_minor=1_000, annual_return=0.05, months=12
        ),
        calc.savings_goal(target_minor=10_000, current_minor=0, monthly_contribution_minor=1_000),
        calc.retirement_estimate(
            current_pot_minor=1_000,
            monthly_contribution_minor=1_000,
            years_to_retirement=10,
            annual_return=0.05,
        ),
        calc.net_worth_projection(
            assets_minor=1_000,
            liabilities_minor=0,
            monthly_saving_minor=100,
            annual_asset_return=0.05,
            monthly_debt_payment_minor=0,
            debt_annual_rate=0.0,
            months=12,
        ),
    ]
    for result in results:
        assert result.assumptions, f"{type(result).__name__} returned no assumptions"
