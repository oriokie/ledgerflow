"""The decision assistant — verdicts, and what they owe the person reading them.

These tests are less about arithmetic than about the shape of an answer. A
verdict that never says no is a salesman; one that lists benefits without costs
is the same thing more politely; one that is confident about a thirty-year
projection is lying. Each of those is pinned below.

The load-bearing one is `test_buy_or_rent_invests_the_renters_deposit`: the
single modelling choice that makes most published buy-vs-rent calculators wrong
is leaving the renter's deposit in cash, and it is invisible unless something
checks for it.
"""

from __future__ import annotations

from datetime import date

from apps.projections import decisions as dec
from apps.projections.engine import DebtPosition, EconomicAssumptions, FinancialPosition

TODAY = date(2026, 1, 31)


def position(**kwargs) -> FinancialPosition:
    base = {
        "currency": "KES",
        "as_of": TODAY,
        "liquid_minor": 8_000_000,
        "investment_minor": 4_000_000,
        "monthly_net_income_minor": 600_000,
        "monthly_expenses_minor": 350_000,
    }
    base.update(kwargs)
    return FinancialPosition(**base)


# ---------------------------------------------------------------------------
# shape of every answer
# ---------------------------------------------------------------------------


def _all_decisions() -> list[dec.Decision]:
    p = position(
        debts=(
            DebtPosition(label="Card", balance_minor=400_000, annual_rate=0.24, monthly_payment_minor=30_000),
        )
    )
    return [
        dec.can_i_afford_mortgage(
            position=p, property_price_minor=30_000_000, deposit_minor=6_000_000, annual_rate=0.09
        ),
        dec.how_much_house(position=p, annual_rate=0.09),
        dec.debt_or_invest(position=p, monthly_amount_minor=50_000, expected_return=0.07),
        dec.can_i_retire(position=p, years_until=25, monthly_income_needed_minor=400_000),
        dec.buy_or_rent(
            position=p,
            property_price_minor=30_000_000,
            deposit_minor=6_000_000,
            annual_rate=0.09,
            monthly_rent_minor=150_000,
        ),
    ]


def test_every_decision_takes_a_position_rather_than_shrugging():
    for decision in _all_decisions():
        assert decision.verdict in vars(dec.Verdict).values()
        assert decision.headline
        assert decision.question


def test_every_decision_states_its_confidence():
    for decision in _all_decisions():
        assert decision.confidence in vars(dec.Confidence).values()


def test_every_decision_states_its_assumptions():
    for decision in _all_decisions():
        if decision.verdict != dec.Verdict.UNKNOWN:
            assert decision.assumptions, f"{decision.question} carries no assumptions"


def test_a_yes_still_lists_what_it_costs():
    """An assistant that only lists benefits is a salesman."""
    decision = dec.can_i_afford_mortgage(
        position=position(), property_price_minor=20_000_000, deposit_minor=5_000_000, annual_rate=0.09
    )
    assert decision.verdict in (dec.Verdict.YES, dec.Verdict.YES_WITH_CARE)
    assert decision.costs


def test_confidence_falls_as_the_horizon_lengthens():
    """A thirty-year answer is mostly a view about returns wearing a number."""
    near = dec.can_i_afford_mortgage(
        position=position(),
        property_price_minor=10_000_000,
        deposit_minor=3_000_000,
        annual_rate=0.09,
        years=3,
    )
    far = dec.can_i_afford_mortgage(
        position=position(),
        property_price_minor=10_000_000,
        deposit_minor=3_000_000,
        annual_rate=0.09,
        years=25,
    )
    assert near.confidence == dec.Confidence.MEASURED
    assert far.confidence == dec.Confidence.ASSUMED


def test_figures_exposes_every_computed_amount_for_the_allow_list():
    decision = dec.can_i_afford_mortgage(
        position=position(), property_price_minor=20_000_000, deposit_minor=5_000_000, annual_rate=0.09
    )
    figures = decision.figures()
    assert figures
    assert 5_000_000 in figures  # the deposit it was given
    assert all(isinstance(f, int) and f >= 0 for f in figures)


# ---------------------------------------------------------------------------
# can I afford this mortgage
# ---------------------------------------------------------------------------


def test_a_comfortable_purchase_is_a_yes():
    decision = dec.can_i_afford_mortgage(
        position=position(), property_price_minor=15_000_000, deposit_minor=4_000_000, annual_rate=0.09
    )
    assert decision.verdict == dec.Verdict.YES


def test_a_deposit_larger_than_savings_is_a_no():
    decision = dec.can_i_afford_mortgage(
        position=position(liquid_minor=1_000_000),
        property_price_minor=20_000_000,
        deposit_minor=5_000_000,
        annual_rate=0.09,
    )
    assert decision.verdict == dec.Verdict.NO
    assert "more than you hold" in decision.headline


def test_a_payment_that_fits_but_drains_the_balance_is_still_a_no():
    """The test most affordability calculators skip, and the reason people pass
    one and then struggle: the payment fits on paper and the household still
    runs out."""
    tight = position(liquid_minor=8_000_000, monthly_net_income_minor=600_000, monthly_expenses_minor=580_000)
    decision = dec.can_i_afford_mortgage(
        position=tight, property_price_minor=20_000_000, deposit_minor=6_000_000, annual_rate=0.12
    )
    assert decision.verdict == dec.Verdict.NO
    assert any("runs out" in r.text or "negative" in r.text for r in decision.risks)


def test_an_over_stretched_payment_is_reported_as_tight():
    decision = dec.can_i_afford_mortgage(
        position=position(monthly_net_income_minor=400_000),
        property_price_minor=20_000_000,
        deposit_minor=4_000_000,
        annual_rate=0.09,
    )
    assert decision.verdict in (dec.Verdict.TIGHT, dec.Verdict.NO)


def test_a_no_offers_a_price_that_would_work():
    """Someone told no is better served by a number they can act on."""
    decision = dec.can_i_afford_mortgage(
        position=position(monthly_net_income_minor=400_000),
        property_price_minor=40_000_000,
        deposit_minor=4_000_000,
        annual_rate=0.09,
    )
    assert decision.alternatives
    assert decision.alternatives[0].amount_minor is not None
    assert decision.alternatives[0].amount_minor < 40_000_000


def test_no_income_is_unknown_rather_than_no():
    """ "We cannot tell" and "no" are different answers and must not be conflated."""
    decision = dec.can_i_afford_mortgage(
        position=position(monthly_net_income_minor=0),
        property_price_minor=10_000_000,
        deposit_minor=2_000_000,
        annual_rate=0.09,
    )
    assert decision.verdict == dec.Verdict.UNKNOWN


def test_the_cost_of_ownership_not_the_quote_is_what_is_tested():
    with_costs = dec.can_i_afford_mortgage(
        position=position(),
        property_price_minor=20_000_000,
        deposit_minor=5_000_000,
        annual_rate=0.09,
        annual_tax_minor=600_000,
        annual_insurance_minor=240_000,
    )
    without = dec.can_i_afford_mortgage(
        position=position(), property_price_minor=20_000_000, deposit_minor=5_000_000, annual_rate=0.09
    )
    cost_with = next(f for f in with_costs.because if f.label == "Monthly cost of ownership")
    cost_without = next(f for f in without.because if f.label == "Monthly cost of ownership")
    assert cost_with.amount_minor > cost_without.amount_minor


# ---------------------------------------------------------------------------
# how much house
# ---------------------------------------------------------------------------


def test_how_much_house_keeps_the_emergency_fund_back():
    """ "You can afford a huge house if you spend every shilling of savings" is
    arithmetically true and practically useless."""
    decision = dec.how_much_house(position=position(), annual_rate=0.09)
    deposit = next(f for f in decision.because if f.label == "Deposit assumed")
    assert deposit.amount_minor < position().liquid_minor


def test_the_two_mortgage_questions_agree_with_each_other():
    """The price `how_much_house` reports must itself pass `can_i_afford`."""
    p = position()
    suggested = dec.how_much_house(position=p, annual_rate=0.09)
    price = next(f for f in suggested.because if f.label == "Price you can carry").amount_minor
    deposit = next(f for f in suggested.because if f.label == "Deposit assumed").amount_minor

    check = dec.can_i_afford_mortgage(
        position=p, property_price_minor=price, deposit_minor=deposit, annual_rate=0.09
    )
    assert check.verdict != dec.Verdict.NO


def test_how_much_house_without_income_is_unknown():
    decision = dec.how_much_house(position=position(monthly_net_income_minor=0), annual_rate=0.09)
    assert decision.verdict == dec.Verdict.UNKNOWN


# ---------------------------------------------------------------------------
# debt or invest
# ---------------------------------------------------------------------------


def test_an_expensive_debt_beats_a_modest_expected_return():
    p = position(
        debts=(
            DebtPosition(
                label="Card", balance_minor=2_000_000, annual_rate=0.28, monthly_payment_minor=60_000
            ),
        )
    )
    decision = dec.debt_or_invest(position=p, monthly_amount_minor=50_000, expected_return=0.05)
    assert decision.verdict == dec.Verdict.YES


def test_the_certainty_gap_is_stated_not_priced():
    """The rule of thumb hides the thing that decides it in practice."""
    p = position(
        debts=(
            DebtPosition(
                label="Loan", balance_minor=1_000_000, annual_rate=0.06, monthly_payment_minor=30_000
            ),
        )
    )
    decision = dec.debt_or_invest(position=p, monthly_amount_minor=50_000, expected_return=0.09)
    assert any("hope" in r.text or "assumption" in r.text for r in decision.risks)


def test_splitting_is_offered_as_the_option_people_actually_keep():
    p = position(
        debts=(
            DebtPosition(
                label="Loan", balance_minor=1_000_000, annual_rate=0.10, monthly_payment_minor=30_000
            ),
        )
    )
    decision = dec.debt_or_invest(position=p, monthly_amount_minor=50_000, expected_return=0.07)
    assert any("Split" in a.label for a in decision.alternatives)


def test_no_debt_makes_the_question_meaningless_rather_than_answered():
    decision = dec.debt_or_invest(position=position(), monthly_amount_minor=50_000, expected_return=0.07)
    assert decision.verdict == dec.Verdict.UNKNOWN


def test_the_extra_goes_to_the_highest_rate_debt():
    p = position(
        debts=(
            DebtPosition(
                label="Cheap", balance_minor=2_000_000, annual_rate=0.04, monthly_payment_minor=40_000
            ),
            DebtPosition(
                label="Expensive", balance_minor=800_000, annual_rate=0.30, monthly_payment_minor=25_000
            ),
        )
    )
    decision = dec.debt_or_invest(position=p, monthly_amount_minor=40_000, expected_return=0.07)
    assert "Expensive" in decision.because[0].text


# ---------------------------------------------------------------------------
# retirement
# ---------------------------------------------------------------------------


def test_a_well_funded_retirement_is_a_yes():
    decision = dec.can_i_retire(
        position=position(investment_minor=200_000_000, liquid_minor=20_000_000),
        years_until=10,
        monthly_income_needed_minor=200_000,
    )
    assert decision.verdict == dec.Verdict.YES


def test_a_shortfall_is_priced_rather_than_just_refused():
    """An advisor who said no and stopped would be fired."""
    decision = dec.can_i_retire(
        position=position(investment_minor=1_000_000, liquid_minor=500_000),
        years_until=10,
        monthly_income_needed_minor=500_000,
    )
    assert decision.verdict in (dec.Verdict.NO, dec.Verdict.TIGHT)
    assert any("more each month" in a.label for a in decision.alternatives)


def test_a_pension_reduces_what_the_pot_must_cover():
    without = dec.can_i_retire(position=position(), years_until=20, monthly_income_needed_minor=400_000)
    with_pension = dec.can_i_retire(
        position=position(),
        years_until=20,
        monthly_income_needed_minor=400_000,
        monthly_pension_income_minor=250_000,
    )
    need_without = next(f for f in without.because if f.label == "What you said you need")
    need_with = next(f for f in with_pension.because if f.label == "What you said you need")
    assert need_with.amount_minor < need_without.amount_minor


def test_sequence_risk_is_always_named():
    decision = dec.can_i_retire(position=position(), years_until=20, monthly_income_needed_minor=300_000)
    assert any("Sequence" in r.label for r in decision.risks)


# ---------------------------------------------------------------------------
# buy or rent
# ---------------------------------------------------------------------------


def test_buy_or_rent_invests_the_renters_deposit():
    """The single modelling choice that makes most published buy-vs-rent
    calculators wrong. Leaving the deposit in cash — at a cash return that
    defaults to zero — hands the comparison to buying, invisibly.

    With a high investment return the renter must do better than with a low
    one; if the deposit were sitting in a current account, the return
    assumption would not touch the renting leg at all.
    """
    p = position()
    args = dict(
        position=p,
        property_price_minor=25_000_000,
        deposit_minor=6_000_000,
        annual_rate=0.09,
        monthly_rent_minor=140_000,
        years=10,
    )
    poor_returns = dec.buy_or_rent(**args, assumptions=EconomicAssumptions(annual_investment_return=0.01))
    good_returns = dec.buy_or_rent(**args, assumptions=EconomicAssumptions(annual_investment_return=0.12))
    rent_poor = next(f for f in poor_returns.because if f.label == "Net worth after renting")
    rent_good = next(f for f in good_returns.because if f.label == "Net worth after renting")
    assert rent_good.amount_minor > rent_poor.amount_minor


def test_buy_or_rent_compares_whole_positions_not_two_payments():
    decision = dec.buy_or_rent(
        position=position(),
        property_price_minor=25_000_000,
        deposit_minor=6_000_000,
        annual_rate=0.09,
        monthly_rent_minor=140_000,
    )
    labels = {f.label for f in decision.because}
    assert {"Net worth after buying", "Net worth after renting"} <= labels


def test_maintenance_is_included_in_the_cost_of_owning():
    """ "Rent is dead money" ignores that owning has costs which are also dead."""
    decision = dec.buy_or_rent(
        position=position(),
        property_price_minor=25_000_000,
        deposit_minor=6_000_000,
        annual_rate=0.09,
        monthly_rent_minor=140_000,
    )
    owning = next(f for f in decision.costs if f.label == "Monthly cost of owning")
    assert owning.amount_minor > 0
    assert any("Maintenance" in a for a in decision.assumptions)


def test_property_growth_is_named_as_the_swing_factor():
    decision = dec.buy_or_rent(
        position=position(),
        property_price_minor=25_000_000,
        deposit_minor=6_000_000,
        annual_rate=0.09,
        monthly_rent_minor=140_000,
    )
    assert any("growth" in r.label.lower() for r in decision.risks)


def test_expensive_rent_favours_buying():
    args = dict(
        position=position(),
        property_price_minor=25_000_000,
        deposit_minor=6_000_000,
        annual_rate=0.09,
        years=10,
    )
    cheap = dec.buy_or_rent(**args, monthly_rent_minor=60_000)
    dear = dec.buy_or_rent(**args, monthly_rent_minor=400_000)
    cheap_gap = (
        next(f for f in cheap.because if f.label == "Net worth after buying").amount_minor
        - next(f for f in cheap.because if f.label == "Net worth after renting").amount_minor
    )
    dear_gap = (
        next(f for f in dear.because if f.label == "Net worth after buying").amount_minor
        - next(f for f in dear.because if f.label == "Net worth after renting").amount_minor
    )
    assert dear_gap > cheap_gap


def test_the_existing_portfolio_is_not_rerated_by_the_expected_return():
    """The regression: the invest leg used to swap the global return assumption
    for the expected one, re-rating the household's *existing* portfolio rather
    than just the money being decided about. With a large portfolio and a small
    monthly amount, the answer was dominated by the re-rating — expected above
    base flattered investing, expected below base flattered the debt, and the
    distortion scaled with wealth instead of with the decision.

    Pinned by asymmetry: for a household with a huge portfolio and a tiny
    decision, the answer must not swing wildly with the expected return the
    way a whole-portfolio re-rating would make it."""
    rich = position(
        investment_minor=100_000_000,
        debts=(
            DebtPosition(label="Loan", balance_minor=500_000, annual_rate=0.10, monthly_payment_minor=20_000),
        ),
    )
    low = dec.debt_or_invest(position=rich, monthly_amount_minor=5_000, expected_return=0.02, months=120)
    high = dec.debt_or_invest(position=rich, monthly_amount_minor=5_000, expected_return=0.12, months=120)

    def gap(decision):
        return next(f for f in decision.because if f.label == "Difference").amount_minor

    # A 10-point swing in expected return, applied to a 5,000/month decision
    # over 10 years, moves the outcome by at most a few hundred thousand minor
    # units. The old whole-portfolio re-rating moved it by tens of millions.
    assert gap(low) < 5_000_000
    assert gap(high) < 5_000_000


def test_how_much_house_scales_to_high_incomes():
    """The search ceiling regression: a fixed upper bound of ten million major
    units silently capped the answer for anyone whose income could carry more.
    The bound is now derived from the annuity closed form, so the answer scales
    with the income rather than with a constant somebody chose."""
    high_earner = position(
        monthly_net_income_minor=100_000_000,  # 1,000,000.00 a month
        liquid_minor=500_000_000,
        monthly_expenses_minor=30_000_000,
    )
    decision = dec.how_much_house(position=high_earner, annual_rate=0.09)
    price = next(f for f in decision.because if f.label == "Price you can carry").amount_minor
    deposit = next(f for f in decision.because if f.label == "Deposit assumed").amount_minor
    # The affordable loan alone (price - deposit) must exceed the old cap.
    assert price - deposit > 1_000_000_000
    # ...and the payment at that price still respects the housing guide.
    payment = next(f for f in decision.because if f.label == "Monthly payment at that price")
    assert payment.amount_minor <= high_earner.monthly_net_income_minor * dec.HOUSING_CEILING
