"""Debt intelligence — rate timelines, compounding, fees, offsets, simulators.

All pure-engine tests: no database, so the arithmetic is pinned directly.

The properties that matter most are the ones a plausible-looking implementation
gets wrong: compounding that doesn't actually differ by frequency, a promo rate
applied retroactively, fees that quietly reduce principal, and a refinance that
reports a saving which never arrives.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.debt import payoff, stress

START = date(2026, 1, 15)
C = payoff.Compounding


def _debt(debt_id="a", balance=500_000, apr="12", minimum=25_000, **kwargs):
    return payoff.DebtInput(
        debt_id=debt_id,
        name=kwargs.pop("name", debt_id),
        balance_minor=balance,
        apr=Decimal(str(apr)),
        minimum_payment_minor=minimum,
        **kwargs,
    )


# =============================================================================
# Compounding frequency
# =============================================================================
def test_compounding_more_often_always_costs_more():
    """The ordering is a mathematical fact, so it makes a strong invariant: if
    this ever fails, a frequency conversion has broken."""
    rates = {
        f: payoff.equivalent_monthly_rate(Decimal("12"), f)
        for f in (C.ANNUAL, C.MONTHLY, C.WEEKLY, C.DAILY, C.CONTINUOUS)
    }
    assert rates[C.ANNUAL] < rates[C.MONTHLY] < rates[C.WEEKLY] < rates[C.DAILY] < rates[C.CONTINUOUS]


def test_monthly_compounding_is_the_plain_division():
    # 12% compounded monthly is exactly 1% a month — no approximation.
    assert payoff.equivalent_monthly_rate(Decimal("12"), C.MONTHLY) == Decimal("0.01")


def test_quarterly_sits_between_annual_and_monthly():
    annual = payoff.equivalent_monthly_rate(Decimal("12"), C.ANNUAL)
    quarterly = payoff.equivalent_monthly_rate(Decimal("12"), C.QUARTERLY)
    monthly = payoff.equivalent_monthly_rate(Decimal("12"), C.MONTHLY)
    assert annual < quarterly < monthly


def test_a_zero_rate_compounds_to_nothing():
    for frequency in C.ALL:
        assert payoff.equivalent_monthly_rate(Decimal("0"), frequency) == 0


def test_an_unknown_frequency_is_rejected():
    with pytest.raises(ValueError):
        payoff.equivalent_monthly_rate(Decimal("12"), "fortnightly")


def test_daily_compounding_costs_more_over_a_full_plan():
    monthly = payoff.simulate([_debt(compounding=C.MONTHLY)], start=START)
    daily = payoff.simulate([_debt(compounding=C.DAILY)], start=START)
    assert daily.total_interest_minor > monthly.total_interest_minor


def test_compounding_is_deterministic():
    """Same inputs, same answer — a plan that shifts between runs is unusable."""
    first = payoff.simulate([_debt(compounding=C.DAILY)], start=START)
    second = payoff.simulate([_debt(compounding=C.DAILY)], start=START)
    assert first.total_interest_minor == second.total_interest_minor
    assert first.months_to_debt_free == second.months_to_debt_free


# =============================================================================
# Variable rates and promotional periods
# =============================================================================
def test_a_debt_with_no_schedule_uses_its_fixed_rate():
    """Backward compatibility: every pre-existing caller passes no schedule."""
    debt = _debt(apr="9.9")
    assert debt.apr_on(START) == Decimal("9.9")
    assert debt.apr_on(date(2030, 1, 1)) == Decimal("9.9")


def test_the_applicable_rate_changes_on_its_effective_date():
    debt = _debt(
        apr="22",
        rate_schedule=(
            payoff.RatePeriod(effective_from=date(2026, 1, 1), apr=Decimal("0")),
            payoff.RatePeriod(effective_from=date(2027, 7, 1), apr=Decimal("22")),
        ),
    )
    # Interest-free during the promo…
    assert debt.apr_on(date(2026, 6, 1)) == Decimal("0")
    assert debt.apr_on(date(2027, 6, 30)) == Decimal("0")
    # …and the standard rate the day it expires.
    assert debt.apr_on(date(2027, 7, 1)) == Decimal("22")


def test_a_schedule_of_only_future_changes_falls_back_to_the_fixed_rate():
    """A partially-specified timeline must degrade to fixed-rate behaviour, not
    to zero — a rate of nothing would silently understate every projection."""
    debt = _debt(
        apr="5.5",
        rate_schedule=(payoff.RatePeriod(effective_from=date(2027, 1, 1), apr=Decimal("8")),),
    )
    assert debt.apr_on(date(2026, 6, 1)) == Decimal("5.5")
    assert debt.apr_on(date(2027, 6, 1)) == Decimal("8")


def test_a_promotional_rate_is_not_applied_retroactively():
    """The expiry must bite from its month onward, not across the whole plan."""
    promo = _debt(
        balance=600_000,
        apr="24",
        minimum=30_000,
        rate_schedule=(
            payoff.RatePeriod(effective_from=date(2026, 1, 1), apr=Decimal("0")),
            payoff.RatePeriod(effective_from=date(2026, 7, 1), apr=Decimal("24")),
        ),
    )
    plan = payoff.simulate([promo], start=START)

    # Nothing charged in the interest-free months…
    assert plan.months[0].total_interest_minor == 0
    # …and real interest once it expires.
    after_expiry = [m for m in plan.months if m.as_of >= date(2026, 7, 1)]
    assert any(m.total_interest_minor > 0 for m in after_expiry)


def test_a_promo_debt_costs_less_than_the_same_debt_at_the_standard_rate():
    standard = _debt(balance=600_000, apr="24", minimum=30_000)
    promo = _debt(
        balance=600_000,
        apr="24",
        minimum=30_000,
        rate_schedule=(
            payoff.RatePeriod(effective_from=date(2026, 1, 1), apr=Decimal("0")),
            payoff.RatePeriod(effective_from=date(2027, 7, 1), apr=Decimal("24")),
        ),
    )
    assert (
        payoff.simulate([promo], start=START).total_interest_minor
        < payoff.simulate([standard], start=START).total_interest_minor
    )


# =============================================================================
# Fees
# =============================================================================
def test_a_monthly_fee_is_charged_every_month_and_tracked_separately():
    debt = _debt(apr="0", fees=payoff.DebtFees(monthly_minor=500))
    plan = payoff.simulate([debt], start=START)

    assert plan.months[0].payments[0].fee_minor == 500
    assert plan.total_fees_minor > 0
    # Separated from interest so a low-rate, high-fee product can't look cheap.
    assert plan.per_debt[0].fees_paid_minor == plan.total_fees_minor


def test_fees_do_not_reduce_the_balance():
    """A fee is a cost of borrowing, not a repayment. Counting it as principal
    would overstate progress every single month."""
    with_fee = _debt(apr="0", minimum=10_000, fees=payoff.DebtFees(monthly_minor=2_000))
    plan = payoff.simulate([with_fee], start=START)

    first = plan.months[0].payments[0]
    assert first.fee_minor == 2_000
    # 100.00 paid, 20.00 of it a fee: only 80.00 came off the balance.
    assert first.principal_minor == 8_000
    assert first.balance_after_minor == 500_000 - 8_000


def test_fees_make_a_debt_take_longer_to_clear():
    plain = payoff.simulate([_debt(apr="0")], start=START)
    fee_laden = payoff.simulate([_debt(apr="0", fees=payoff.DebtFees(monthly_minor=2_000))], start=START)
    assert fee_laden.months_to_debt_free > plain.months_to_debt_free


def test_an_annual_fee_lands_in_one_month_not_spread_across_twelve():
    """Smoothing it would hide a real hit behind a small average."""
    debt = _debt(apr="0", fees=payoff.DebtFees(annual_minor=15_000, annual_month=3))
    plan = payoff.simulate([debt], start=START)

    march = [m for m in plan.months if m.as_of.month == 3]
    other = [m for m in plan.months if m.as_of.month not in (3,)]
    assert march and march[0].total_fees_minor == 15_000
    assert all(m.total_fees_minor == 0 for m in other)


def test_an_origination_fee_is_charged_once_at_the_start():
    debt = _debt(apr="0", fees=payoff.DebtFees(origination_minor=25_000))
    plan = payoff.simulate([debt], start=START)
    assert plan.months[0].total_fees_minor == 25_000
    assert all(m.total_fees_minor == 0 for m in plan.months[1:])


def test_a_debt_with_no_fees_reports_none():
    plan = payoff.simulate([_debt(apr="0")], start=START)
    assert plan.total_fees_minor == 0


# =============================================================================
# Offset accounts
# =============================================================================
def test_an_offset_reduces_the_interest_bearing_balance():
    without = payoff.simulate([_debt(balance=1_000_000, apr="6")], start=START)
    with_offset = payoff.simulate([_debt(balance=1_000_000, apr="6", offset_minor=400_000)], start=START)
    assert with_offset.total_interest_minor < without.total_interest_minor
    assert with_offset.months_to_debt_free < without.months_to_debt_free


def test_an_offset_never_changes_the_debt_balance():
    """The offset account's money is still the user's — it reduces the interest
    charged, it does not repay anything."""
    plan = payoff.simulate([_debt(balance=1_000_000, apr="6", offset_minor=400_000)], start=START)
    assert plan.per_debt[0].starting_balance_minor == 1_000_000


def test_an_offset_larger_than_the_debt_stops_interest_entirely():
    plan = payoff.simulate([_debt(balance=100_000, apr="20", offset_minor=500_000)], start=START)
    # It stops the interest; it doesn't earn a credit.
    assert plan.total_interest_minor == 0


def test_a_zero_offset_behaves_as_if_absent():
    assert (
        payoff.simulate([_debt(offset_minor=0)], start=START).total_interest_minor
        == payoff.simulate([_debt()], start=START).total_interest_minor
    )


# =============================================================================
# Flexible extra payments
# =============================================================================
def test_a_constant_extra_is_just_the_simplest_schedule():
    """Normalising one into the other means there's only one code path."""
    flat = payoff.simulate([_debt()], extra_monthly_minor=10_000, start=START)
    via_schedule = payoff.simulate([_debt()], extra=payoff.ExtraPayments(monthly_minor=10_000), start=START)
    assert flat.months_to_debt_free == via_schedule.months_to_debt_free
    assert flat.total_interest_minor == via_schedule.total_interest_minor


def test_a_lump_sum_lands_in_its_month_only():
    extra = payoff.ExtraPayments(lump_sums=((3, 100_000),))
    assert extra.for_month(2) == 0
    assert extra.for_month(3) == 100_000
    assert extra.for_month(4) == 0


def test_a_step_up_persists_from_its_month_onward():
    extra = payoff.ExtraPayments(monthly_minor=5_000, step_ups=((6, 20_000),))
    assert extra.for_month(5) == 5_000
    assert extra.for_month(6) == 20_000
    assert extra.for_month(60) == 20_000


def test_the_most_recent_step_up_wins_not_the_largest():
    """A later reduction is as real as a later increase — taking the maximum
    would quietly ignore someone telling us their circumstances worsened."""
    extra = payoff.ExtraPayments(step_ups=((3, 50_000), (9, 10_000)))
    assert extra.for_month(5) == 50_000
    assert extra.for_month(12) == 10_000


def test_a_lump_sum_shortens_the_plan():
    without = payoff.simulate([_debt()], start=START)
    with_bonus = payoff.simulate(
        [_debt()], extra=payoff.ExtraPayments(lump_sums=((2, 200_000),)), start=START
    )
    assert with_bonus.months_to_debt_free < without.months_to_debt_free


def test_a_future_lump_sum_stops_a_plan_being_called_impossible():
    """Without this, a debt that stalls now but is rescued in month six would
    be reported as never clearing — a false and discouraging answer."""
    stuck = _debt(balance=500_000, apr="24", minimum=5_000)
    assert payoff.simulate([stuck], start=START).months_to_debt_free is None

    rescued = payoff.simulate([stuck], extra=payoff.ExtraPayments(lump_sums=((6, 600_000),)), start=START)
    assert rescued.months_to_debt_free is not None
    assert rescued.stuck_debt_ids == []


# =============================================================================
# Refinance
# =============================================================================
def test_refinancing_to_a_lower_rate_saves_money():
    debt = _debt(balance=2_000_000, apr="18", minimum=50_000)
    quote = payoff.RefinanceQuote(
        new_apr=Decimal("7"), new_minimum_payment_minor=50_000, closing_costs_minor=50_000
    )
    result = payoff.simulate_refinance(debt, quote, start=START)

    assert result.lifetime_saving_minor > 0
    assert result.is_worthwhile is True
    assert result.breakeven_month is not None


def test_refinancing_never_touches_the_original_debt():
    debt = _debt(balance=2_000_000, apr="18", minimum=50_000)
    payoff.simulate_refinance(
        debt,
        payoff.RefinanceQuote(new_apr=Decimal("7"), new_minimum_payment_minor=50_000),
        start=START,
    )
    # Simulation only — the input is frozen and unchanged.
    assert debt.balance_minor == 2_000_000
    assert debt.apr == Decimal("18")


def test_a_worse_rate_is_reported_as_not_worthwhile():
    debt = _debt(balance=2_000_000, apr="6", minimum=50_000)
    result = payoff.simulate_refinance(
        debt,
        payoff.RefinanceQuote(new_apr=Decimal("15"), new_minimum_payment_minor=50_000),
        start=START,
    )
    assert result.lifetime_saving_minor < 0
    assert result.is_worthwhile is False


def test_closing_costs_can_be_capitalised_or_paid_up_front():
    debt = _debt(balance=2_000_000, apr="18", minimum=50_000)
    rolled = payoff.simulate_refinance(
        debt,
        payoff.RefinanceQuote(
            new_apr=Decimal("7"),
            new_minimum_payment_minor=50_000,
            closing_costs_minor=100_000,
            capitalise_costs=True,
        ),
        start=START,
    )
    upfront = payoff.simulate_refinance(
        debt,
        payoff.RefinanceQuote(
            new_apr=Decimal("7"),
            new_minimum_payment_minor=50_000,
            closing_costs_minor=100_000,
            capitalise_costs=False,
        ),
        start=START,
    )
    # Rolling the costs in means paying interest on them, so it costs more.
    assert rolled.new_total_cost_minor > upfront.new_total_cost_minor


def test_breakeven_is_reported_because_a_saving_that_never_arrives_is_not_one():
    """Huge closing costs against a marginal rate cut: the lifetime figure may
    still be positive, but the month it turns is what decides it."""
    debt = _debt(balance=2_000_000, apr="8", minimum=50_000)
    result = payoff.simulate_refinance(
        debt,
        payoff.RefinanceQuote(
            new_apr=Decimal("7.5"),
            new_minimum_payment_minor=50_000,
            closing_costs_minor=400_000,
            capitalise_costs=False,
        ),
        start=START,
    )
    # Either it never breaks even, or it takes long enough to be worth stating.
    assert result.breakeven_month is None or result.breakeven_month > 12


# =============================================================================
# Consolidation
# =============================================================================
def test_consolidation_compares_total_cost_not_the_monthly_payment():
    """Consolidation almost always lowers the monthly figure — that's its
    selling point. Judging it on that would recommend every offer."""
    debts = [
        _debt("a", balance=500_000, apr="24", minimum=20_000, name="Card A"),
        _debt("b", balance=300_000, apr="19", minimum=15_000, name="Card B"),
    ]
    result = payoff.simulate_consolidation(
        debts,
        payoff.ConsolidationQuote(new_apr=Decimal("9"), new_minimum_payment_minor=35_000),
        start=START,
    )
    assert result is not None
    assert result.combined_balance_minor == 800_000
    assert result.current_weighted_apr > result.new_apr
    assert result.is_worthwhile is True


def test_a_longer_cheaper_loan_can_still_cost_more_overall():
    """The trap consolidation adverts rely on: a lower rate and a lower payment
    that together cost more because the term stretches."""
    debts = [
        _debt("a", balance=400_000, apr="14", minimum=40_000, name="A"),
        _debt("b", balance=400_000, apr="14", minimum=40_000, name="B"),
    ]
    result = payoff.simulate_consolidation(
        debts,
        # Lower rate, but a payment less than half the current total.
        payoff.ConsolidationQuote(new_apr=Decimal("11"), new_minimum_payment_minor=25_000),
        start=START,
    )
    assert result.new_monthly_minor < result.current_monthly_minor
    assert result.new_total_cost_minor > result.current_total_cost_minor
    # Judged on lifetime cost, so the cheaper-looking option isn't mistaken for
    # the cheaper one.
    assert result.is_worthwhile is False


def test_consolidation_needs_at_least_two_debts():
    assert (
        payoff.simulate_consolidation(
            [_debt()],
            payoff.ConsolidationQuote(new_apr=Decimal("9"), new_minimum_payment_minor=20_000),
            start=START,
        )
        is None
    )


def test_consolidation_fees_are_added_to_the_new_balance():
    debts = [
        _debt("a", balance=400_000, apr="20", minimum=20_000),
        _debt("b", balance=400_000, apr="20", minimum=20_000),
    ]
    without = payoff.simulate_consolidation(
        debts,
        payoff.ConsolidationQuote(new_apr=Decimal("9"), new_minimum_payment_minor=40_000),
        start=START,
    )
    with_fees = payoff.simulate_consolidation(
        debts,
        payoff.ConsolidationQuote(new_apr=Decimal("9"), new_minimum_payment_minor=40_000, fees_minor=50_000),
        start=START,
    )
    assert with_fees.new_total_cost_minor > without.new_total_cost_minor


# =============================================================================
# Debt stress score
# =============================================================================
def test_no_debt_scores_perfectly():
    assert stress.compute(stress.StressInputs()).score == 100


def test_higher_is_better_matching_the_health_score():
    """Inverting one relative to the other would be a persistent misread."""
    comfortable = stress.compute(
        stress.StressInputs(
            total_balance_minor=200_000,
            total_minimum_minor=10_000,
            monthly_interest_minor=500,
            monthly_income_minor=400_000,
            weighted_apr=4.0,
            months_to_debt_free=18,
        )
    )
    struggling = stress.compute(
        stress.StressInputs(
            total_balance_minor=8_000_000,
            total_minimum_minor=200_000,
            monthly_interest_minor=150_000,
            monthly_income_minor=300_000,
            weighted_apr=26.0,
            months_to_debt_free=200,
        )
    )
    assert comfortable.score > struggling.score
    assert comfortable.band in ("excellent", "good")
    assert struggling.band in ("high", "critical")


def test_missing_income_is_excluded_rather_than_treated_as_zero():
    """Scoring an absent income as nothing would produce an alarming number
    derived from a gap in the data."""
    without = stress.compute(
        stress.StressInputs(
            total_balance_minor=500_000,
            total_minimum_minor=20_000,
            monthly_interest_minor=5_000,
            weighted_apr=12.0,
        )
    )
    keys = {c.key for c in without.components}
    assert "debt_to_income" not in keys
    assert "minimum_payment_ratio" not in keys
    # And it says how much of the score was actually measurable.
    assert without.coverage < 1.0
    assert without.is_provisional is True


def test_full_data_gives_full_coverage():
    score = stress.compute(
        stress.StressInputs(
            total_balance_minor=1_000_000,
            total_minimum_minor=40_000,
            monthly_interest_minor=10_000,
            monthly_income_minor=350_000,
            total_credit_limit_minor=1_500_000,
            revolving_balance_minor=600_000,
            weighted_apr=15.0,
            months_to_debt_free=40,
        )
    )
    assert score.coverage == 1.0
    assert score.is_provisional is False
    assert len(score.components) == 6


def test_a_plan_that_never_clears_scores_zero_on_duration():
    score = stress.compute(
        stress.StressInputs(
            total_balance_minor=500_000,
            total_minimum_minor=5_000,
            monthly_interest_minor=10_000,
            months_to_debt_free=None,
        )
    )
    duration = next(c for c in score.components if c.key == "payoff_duration")
    assert duration.score == 0
    assert "never clears" in duration.detail


def test_missed_payments_apply_a_penalty_rather_than_being_averaged_away():
    """Averaging them against a good utilisation figure would let a real
    problem hide behind an unrelated strength."""
    base = stress.StressInputs(
        total_balance_minor=500_000,
        total_minimum_minor=20_000,
        monthly_interest_minor=4_000,
        monthly_income_minor=400_000,
        weighted_apr=10.0,
        months_to_debt_free=24,
    )
    clean = stress.compute(base)
    # `slots=True` means no __dict__; replace() is the right tool regardless.
    missed = stress.compute(replace(base, missed_payments_12m=3))
    assert missed.score < clean.score
    assert missed.missed_payment_penalty == 24


def test_the_penalty_is_capped():
    score = stress.compute(
        stress.StressInputs(
            total_balance_minor=100_000,
            total_minimum_minor=10_000,
            monthly_income_minor=500_000,
            missed_payments_12m=99,
        )
    )
    assert score.missed_payment_penalty == 25


def test_the_score_is_bounded():
    for missed in (0, 5, 50):
        score = stress.compute(
            stress.StressInputs(
                total_balance_minor=20_000_000,
                total_minimum_minor=500_000,
                monthly_interest_minor=400_000,
                monthly_income_minor=200_000,
                weighted_apr=29.9,
                months_to_debt_free=None,
                missed_payments_12m=missed,
            )
        )
        assert 0 <= score.score <= 100


def test_the_explanation_leads_with_the_weakest_component():
    """The lowest-scoring component is where an improvement moves the total
    most — the only actionable thing a composite score has to say."""
    score = stress.compute(
        stress.StressInputs(
            total_balance_minor=1_000_000,
            total_minimum_minor=40_000,
            monthly_interest_minor=35_000,
            monthly_income_minor=500_000,
            weighted_apr=27.0,
            months_to_debt_free=30,
        )
    )
    explanation = stress.explain(score)
    assert explanation["weakest"] == explanation["components"][0]["key"]
    assert all(c["detail"] for c in explanation["components"])
    assert explanation["method"]


def test_every_component_explains_itself():
    score = stress.compute(
        stress.StressInputs(
            total_balance_minor=1_000_000,
            total_minimum_minor=40_000,
            monthly_interest_minor=10_000,
            monthly_income_minor=350_000,
            total_credit_limit_minor=1_500_000,
            revolving_balance_minor=600_000,
            weighted_apr=15.0,
            months_to_debt_free=40,
        )
    )
    # A score someone can't interrogate is one they'll over-trust or ignore.
    for component in score.components:
        assert component.detail.strip()
        assert 0 <= component.score <= 100


# =============================================================================
# Integration: stored terms feeding the engine
# =============================================================================
import uuid  # noqa: E402

from apps.debt import selectors as debt_selectors  # noqa: E402
from apps.debt import services as debt_services  # noqa: E402
from apps.debt.models import Compounding as ModelCompounding  # noqa: E402
from apps.debt.models import DebtKind, DebtRateHistory  # noqa: E402
from apps.finance import services as finance_services  # noqa: E402
from apps.finance.models import AccountType  # noqa: E402
from tests.utils import tenant_scope  # noqa: E402

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _card(name="Card", balance=500_000, apr="19.9", minimum=25_000, **terms):
    account = finance_services.create_financial_account(
        name=name,
        account_type=AccountType.CREDIT_CARD,
        currency="USD",
        opening_balance_minor=balance,
    )
    debt_services.set_debt_terms(
        financial_account=account,
        apr=apr,
        minimum_payment_minor=minimum,
        debt_kind=DebtKind.CREDIT_CARD,
        **terms,
    )
    return account


def test_model_and_engine_compounding_choices_agree():
    """Duplicated deliberately — the engine can't import Django — so this test
    is what stops the two drifting apart."""
    assert set(ModelCompounding.values) == set(payoff.Compounding.ALL)


def test_recorded_rate_changes_build_the_engine_timeline(tenant):
    with tenant_scope(tenant):
        account = _card(apr="12")
        debt_services.record_rate_change(
            financial_account=account, apr="15.5", effective_from=date(2027, 1, 1)
        )
        [view] = debt_selectors.debt_views(as_of=date(2026, 6, 1))

        assert view.next_rate_change_on == date(2027, 1, 1)
        assert view.next_rate_apr == Decimal("15.500")
        # Not yet in force, so today's rate is unchanged.
        assert view.apr == Decimal("12")


def test_a_rate_in_force_supersedes_the_flat_field(tenant):
    with tenant_scope(tenant):
        account = _card(apr="12")
        debt_services.record_rate_change(financial_account=account, apr="18", effective_from=date(2026, 1, 1))
        [view] = debt_selectors.debt_views(as_of=date(2026, 6, 1))
        assert view.apr == Decimal("18.000")


def test_rate_history_is_append_only_per_date(tenant):
    """Re-recording the same date corrects that entry; it doesn't create a
    second rate for one morning."""
    with tenant_scope(tenant):
        account = _card()
        debt_services.record_rate_change(financial_account=account, apr="15", effective_from=date(2027, 1, 1))
        debt_services.record_rate_change(financial_account=account, apr="16", effective_from=date(2027, 1, 1))
        assert DebtRateHistory.objects.count() == 1
        assert DebtRateHistory.objects.get().apr == Decimal("16.000")


def test_rate_changes_need_terms_first(tenant):
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Card", account_type=AccountType.CREDIT_CARD, currency="USD"
        )
        with pytest.raises(debt_services.DebtError):
            debt_services.record_rate_change(
                financial_account=account, apr="10", effective_from=date(2027, 1, 1)
            )


def test_legacy_promotional_fields_become_a_rate_timeline(tenant):
    """Existing promo data must keep working without migrating it."""
    with tenant_scope(tenant):
        _card(
            apr="22",
            promotional_apr="0",
            promotional_apr_until=date(2027, 6, 30),
            opened_on=date(2026, 1, 1),
        )
        [view] = debt_selectors.debt_views(as_of=date(2026, 6, 1))

        assert view.apr == Decimal("0")
        assert view.promo_ends_on == date(2027, 6, 30)
        assert view.promo_days_remaining is not None and view.promo_days_remaining > 0
        # And the timeline hands the engine the standard rate after expiry.
        schedule = view.rate_schedule
        assert any(p.apr == Decimal("22") for p in schedule)


def test_a_fixed_rate_debt_gets_no_schedule_at_all(tenant):
    """Backward compatibility: nothing changes for debts without timelines."""
    with tenant_scope(tenant):
        _card(apr="9.9")
        [view] = debt_selectors.debt_views()
        assert view.rate_schedule == ()
        assert view.apr == Decimal("9.9")


def test_compounding_flows_from_the_profile_into_the_plan(tenant):
    with tenant_scope(tenant):
        _card(name="Daily card", apr="18", compounding=ModelCompounding.DAILY)
        [view] = debt_selectors.debt_views()
        assert view.compounding == "daily"

        inputs = debt_selectors.to_debt_inputs([view])
        assert inputs[0].compounding == "daily"


def test_fees_flow_into_the_borrowing_cost_breakdown(tenant):
    with tenant_scope(tenant):
        _card(apr="0", monthly_fee_minor=500, annual_fee_minor=9_900)

        cost = debt_selectors.borrowing_cost()
        assert cost is not None
        assert cost.monthly_fees_minor == 500
        # 12 monthly fees plus the annual one.
        assert cost.annual_fees_minor == 500 * 12 + 9_900
        # Interest and fees stay separate so a fee-heavy card can't look cheap.
        assert cost.annual_interest_minor == 0
        assert cost.fee_share == 100.0


def test_offset_accounts_reduce_interest_without_moving_money(tenant):
    with tenant_scope(tenant):
        mortgage = finance_services.create_financial_account(
            name="Mortgage",
            account_type=AccountType.LOAN,
            currency="USD",
            opening_balance_minor=20_000_000,
        )
        debt_services.set_debt_terms(
            financial_account=mortgage,
            apr="5",
            minimum_payment_minor=120_000,
            debt_kind=DebtKind.MORTGAGE,
        )
        savings = finance_services.create_financial_account(
            name="Offset savings",
            account_type=AccountType.SAVINGS,
            currency="USD",
            opening_balance_minor=5_000_000,
        )

        before = debt_selectors.debt_views()[0].monthly_interest_minor
        debt_services.set_offset_accounts(financial_account=mortgage, account_ids=[savings.id])
        view = next(v for v in debt_selectors.debt_views() if v.name == "Mortgage")

        assert view.offset_minor == 5_000_000
        assert view.monthly_interest_minor < before
        # Neither balance moved — offsetting is an arrangement, not a transfer.
        assert view.balance_minor == 20_000_000


def test_a_debt_cannot_offset_another_debt(tenant):
    with tenant_scope(tenant):
        loan = _card(name="Loan")
        other = _card(name="Other card")
        with pytest.raises(debt_services.DebtError, match="asset accounts"):
            debt_services.set_offset_accounts(financial_account=loan, account_ids=[other.id])


def test_offsets_must_match_the_debt_currency(tenant):
    with tenant_scope(tenant):
        card = _card()
        eur = finance_services.create_financial_account(
            name="EUR savings", account_type=AccountType.SAVINGS, currency="EUR"
        )
        with pytest.raises(debt_services.DebtError, match="currency"):
            debt_services.set_offset_accounts(financial_account=card, account_ids=[eur.id])


def test_stress_score_is_derived_and_explained(tenant):
    with tenant_scope(tenant):
        _card(name="Card", balance=800_000, apr="24", minimum=25_000)

        result = debt_selectors.debt_stress()
        assert result is not None
        assert 0 <= result["score"] <= 100
        assert result["band"] in ("excellent", "good", "moderate", "high", "critical")
        # Every component justifies itself, and the weakest leads.
        assert result["components"]
        assert result["weakest"] == result["components"][0]["key"]
        assert result["method"]


def test_stress_score_is_none_without_debt(tenant):
    with tenant_scope(tenant):
        assert debt_selectors.debt_stress() is None


# =============================================================================
# API surface
# =============================================================================
def _api_card(client, name="Card", balance=800_000, apr="19.9", minimum=30_000, **terms):
    account = client.post(
        "/api/v1/finance/accounts/",
        {"name": name, "account_type": "credit_card", "currency": "USD", "opening_balance_minor": balance},
        format="json",
    ).data
    payload = {"apr": apr, "minimum_payment_minor": minimum, "debt_kind": "credit_card"}
    payload.update(terms)
    resp = client.put(f"/api/v1/debt/debts/{account['id']}/terms/", payload, format="json")
    assert resp.status_code == 200, resp.data
    return account


def test_api_rate_history_round_trip(tenant_context):
    _, client = tenant_context
    account = _api_card(client, apr="12")

    posted = client.post(
        f"/api/v1/debt/debts/{account['id']}/rates/",
        {"apr": "15.5", "effective_from": "2027-01-01", "source": "lender"},
        format="json",
    )
    assert posted.status_code == 201, posted.data

    history = client.get(f"/api/v1/debt/debts/{account['id']}/rates/").data
    assert history["current_apr"] == 12.0
    # DRF hands back a date object pre-render; compare like for like.
    assert history["next_change_on"] == date(2027, 1, 1)
    assert history["next_apr"] == 15.5
    assert history["historical_average_apr"] is not None


def test_api_compounding_and_fees_round_trip(tenant_context):
    _, client = tenant_context
    _api_card(client, apr="0", compounding="daily", monthly_fee_minor=500, annual_fee_minor=9_900)

    [debt] = client.get("/api/v1/debt/debts/").data
    assert debt["compounding"] == "daily"
    assert debt["fees"]["monthly_minor"] == 500

    cost = client.get("/api/v1/debt/debts/borrowing-cost/").data
    assert cost["annual_fees_minor"] == 500 * 12 + 9_900
    # Interest and fees reported apart, so a fee-heavy product can't look cheap.
    assert cost["annual_interest_minor"] == 0
    assert cost["fee_share"] == 100.0


def test_api_offset_accounts_reduce_interest(tenant_context):
    _, client = tenant_context
    account = _api_card(client, name="Mortgage", balance=20_000_000, apr="5", minimum=120_000)
    savings = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Offset", "account_type": "savings", "currency": "USD", "opening_balance_minor": 5_000_000},
        format="json",
    ).data

    before = client.get("/api/v1/debt/debts/").data[0]["monthly_interest_minor"]
    resp = client.put(
        f"/api/v1/debt/debts/{account['id']}/offsets/",
        {"account_ids": [savings["id"]]},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["offset_minor"] == 5_000_000
    assert resp.data["monthly_interest_minor"] < before
    # Offsetting is an arrangement, not a transfer — the balance is untouched.
    assert resp.data["balance_minor"] == 20_000_000


def test_api_refinance_simulation_never_modifies_the_debt(tenant_context):
    _, client = tenant_context
    account = _api_card(client, balance=2_000_000, apr="18", minimum=50_000)

    result = client.post(
        f"/api/v1/debt/debts/{account['id']}/refinance/",
        {"new_apr": "7", "new_minimum_payment_minor": 50_000, "closing_costs_minor": 50_000},
        format="json",
    )
    assert result.status_code == 200, result.data
    assert result.data["lifetime_saving_minor"] > 0
    assert result.data["breakeven_month"] is not None

    # Simulation only.
    [debt] = client.get("/api/v1/debt/debts/").data
    assert debt["apr"] == 18.0
    assert debt["balance_minor"] == 2_000_000


def test_api_consolidation_compares_lifetime_cost(tenant_context):
    _, client = tenant_context
    a = _api_card(client, name="Card A", balance=500_000, apr="24", minimum=20_000)
    b = _api_card(client, name="Card B", balance=300_000, apr="19", minimum=15_000)

    result = client.post(
        "/api/v1/debt/debts/consolidate/",
        {"account_ids": [a["id"], b["id"]], "new_apr": "9", "new_minimum_payment_minor": 35_000},
        format="json",
    )
    assert result.status_code == 200, result.data
    assert result.data["combined_balance_minor"] == 800_000
    assert result.data["current_weighted_apr"] > result.data["new_apr"]
    assert result.data["is_worthwhile"] is True


def test_api_consolidation_needs_two_debts(tenant_context):
    _, client = tenant_context
    a = _api_card(client)
    resp = client.post(
        "/api/v1/debt/debts/consolidate/",
        {"account_ids": [a["id"]], "new_apr": "9", "new_minimum_payment_minor": 20_000},
        format="json",
    )
    assert resp.status_code == 400


def test_api_scenario_comparison(tenant_context):
    _, client = tenant_context
    _api_card(client, balance=800_000, apr="18", minimum=30_000)

    resp = client.post(
        "/api/v1/debt/debts/scenarios/",
        {
            "scenarios": [
                {"label": "Steady £100", "monthly_minor": 10_000},
                {"label": "Bonus in March", "lump_sums": [[3, 200_000]]},
                {"label": "Raise from month 9", "step_ups": [[9, 30_000]]},
            ]
        },
        format="json",
    )
    assert resp.status_code == 200, resp.data
    labels = [s["label"] for s in resp.data["scenarios"]]
    assert labels == ["Steady £100", "Bonus in March", "Raise from month 9"]
    # Every scenario is measured against doing nothing, so each saves something.
    assert all(s["interest_saved_minor"] > 0 for s in resp.data["scenarios"])
    assert resp.data["baseline"]["months_to_debt_free"] is not None


def test_api_stress_score_explains_itself(tenant_context):
    _, client = tenant_context
    _api_card(client, balance=900_000, apr="26", minimum=25_000)

    data = client.get("/api/v1/debt/debts/stress/").data
    assert 0 <= data["score"] <= 100
    assert data["band"] in ("excellent", "good", "moderate", "high", "critical")
    assert data["components"]
    assert data["weakest"] == data["components"][0]["key"]
    assert data["method"]


def test_api_stress_is_204_without_debt(tenant_context):
    _, client = tenant_context
    assert client.get("/api/v1/debt/debts/stress/").status_code == 204


def test_existing_payoff_endpoint_is_unchanged(tenant_context):
    """Backward compatibility: the original contract still holds."""
    _, client = tenant_context
    _api_card(client, name="A", balance=100_000, apr="0", minimum=20_000)
    _api_card(client, name="B", balance=200_000, apr="0", minimum=20_000)

    data = client.get("/api/v1/debt/debts/payoff/?strategy=snowball&extra_monthly_minor=10000&months=6").data
    assert data["strategy"] == "snowball"
    assert data["is_complete"] is True
    assert data["calendar"]
    assert {c["strategy"] for c in data["comparison"]} == {"avalanche", "snowball", "custom"}


# =============================================================================
# Debt signals (coach + alerts)
# =============================================================================
def test_a_promo_nearing_expiry_is_flagged_with_a_countdown(tenant):
    with tenant_scope(tenant):
        today = date.today()
        _card(
            name="Store card",
            balance=600_000,
            apr="24",
            promotional_apr="0",
            promotional_apr_until=today + timedelta(days=21),
            opened_on=today - timedelta(days=300),
        )
        signals = debt_selectors.debt_signals()
        promo = next(s for s in signals if s.kind == "promo_expiry")

        assert "21 days" in promo.title
        # Says what it will start costing, which is the actionable part.
        assert promo.evidence["standard_apr"] == 24.0
        assert promo.evidence["balance_minor"] == 600_000


def test_a_distant_promo_is_not_flagged(tenant):
    with tenant_scope(tenant):
        today = date.today()
        _card(
            apr="24",
            promotional_apr="0",
            promotional_apr_until=today + timedelta(days=400),
            opened_on=today,
        )
        # Warning about something a year away just trains people to ignore it.
        assert not [s for s in debt_selectors.debt_signals() if s.kind == "promo_expiry"]


def test_a_notified_rate_rise_is_surfaced_before_it_bites(tenant):
    with tenant_scope(tenant):
        account = _card(apr="12")
        debt_services.record_rate_change(
            financial_account=account,
            apr="18",
            effective_from=date.today() + timedelta(days=30),
            source="lender",
        )
        rise = next(s for s in debt_selectors.debt_signals() if s.kind == "rate_increase")
        assert rise.evidence["current_apr"] == 12.0
        assert rise.evidence["new_apr"] == 18.0


def test_a_rate_cut_is_not_reported_as_an_increase(tenant):
    with tenant_scope(tenant):
        account = _card(apr="18")
        debt_services.record_rate_change(
            financial_account=account, apr="9", effective_from=date.today() + timedelta(days=30)
        )
        assert not [s for s in debt_selectors.debt_signals() if s.kind == "rate_increase"]


def test_a_fee_heavy_debt_is_flagged_with_why_it_matters(tenant):
    with tenant_scope(tenant):
        _card(name="Premium card", apr="2", balance=200_000, monthly_fee_minor=1_500)
        fees = next(s for s in debt_selectors.debt_signals() if s.kind == "high_fees")
        # The genuinely useful point: fees don't shrink as you repay.
        assert "won't reduce it" in fees.body
        assert "don't fall as you repay" in fees.rationale


def test_a_low_fee_debt_is_not_flagged(tenant):
    with tenant_scope(tenant):
        _card(apr="20", balance=500_000, monthly_fee_minor=100)
        assert not [s for s in debt_selectors.debt_signals() if s.kind == "high_fees"]


def test_idle_savings_against_a_mortgage_suggests_offsetting(tenant):
    with tenant_scope(tenant):
        mortgage = finance_services.create_financial_account(
            name="Mortgage",
            account_type=AccountType.LOAN,
            currency="USD",
            opening_balance_minor=20_000_000,
        )
        debt_services.set_debt_terms(
            financial_account=mortgage,
            apr="5",
            minimum_payment_minor=120_000,
            debt_kind=DebtKind.MORTGAGE,
        )
        finance_services.create_financial_account(
            name="Savings",
            account_type=AccountType.SAVINGS,
            currency="USD",
            opening_balance_minor=3_000_000,
        )

        offset = next(s for s in debt_selectors.debt_signals() if s.kind == "offset_opportunity")
        assert offset.evidence["monthly_saving_minor"] > 0
        # The money stays available — that's what makes offsetting attractive.
        assert "stays yours" in offset.rationale


def test_offsetting_is_not_suggested_once_it_is_set_up(tenant):
    with tenant_scope(tenant):
        mortgage = finance_services.create_financial_account(
            name="Mortgage",
            account_type=AccountType.LOAN,
            currency="USD",
            opening_balance_minor=20_000_000,
        )
        debt_services.set_debt_terms(
            financial_account=mortgage,
            apr="5",
            minimum_payment_minor=120_000,
            debt_kind=DebtKind.MORTGAGE,
        )
        savings = finance_services.create_financial_account(
            name="Savings",
            account_type=AccountType.SAVINGS,
            currency="USD",
            opening_balance_minor=3_000_000,
        )
        debt_services.set_offset_accounts(financial_account=mortgage, account_ids=[savings.id])
        assert not [s for s in debt_selectors.debt_signals() if s.kind == "offset_opportunity"]


def test_the_most_expensive_debt_is_identified_without_claiming_a_product_exists(tenant):
    with tenant_scope(tenant):
        _card(name="Cheap loan", balance=1_000_000, apr="4", minimum=20_000)
        _card(name="Expensive card", balance=500_000, apr="27", minimum=15_000)

        refi = next(s for s in debt_selectors.debt_signals() if s.kind == "refinance_opportunity")
        assert "Expensive card" in refi.title
        # Careful wording: we have no rate data, so we don't promise an offer.
        assert "depends" in refi.rationale


def test_progress_milestones_are_reported(tenant):
    """A planner that only ever reports problems is one people stop opening."""
    with tenant_scope(tenant):
        _card(name="Car loan", balance=250_000, original_principal_minor=1_000_000)
        milestone = next(s for s in debt_selectors.debt_signals() if s.kind == "debt_milestone")
        assert "75% repaid" in milestone.title


def test_a_milestone_needs_the_original_principal(tenant):
    with tenant_scope(tenant):
        _card(name="Unknown start")
        # A balance alone can't say how far through you are.
        assert not [s for s in debt_selectors.debt_signals() if s.kind == "debt_milestone"]


def test_signals_are_ordered_by_severity(tenant):
    with tenant_scope(tenant):
        today = date.today()
        _card(
            name="Urgent",
            balance=600_000,
            apr="24",
            promotional_apr="0",
            promotional_apr_until=today + timedelta(days=7),
            opened_on=today - timedelta(days=300),
        )
        _card(name="Milestone", balance=250_000, original_principal_minor=1_000_000)

        signals = debt_selectors.debt_signals()
        order = {"critical": 0, "warning": 1, "opportunity": 2, "info": 3}
        assert [order[s.severity] for s in signals] == sorted(order[s.severity] for s in signals)


def test_no_debt_produces_no_signals(tenant):
    with tenant_scope(tenant):
        assert debt_selectors.debt_signals() == []


def test_debt_signals_reach_the_coach_as_insights(tenant):
    """The debt app owns the analysis; the coach adapts it. Recomputing here
    would let the two disagree about the same debt."""
    from apps.intelligence import coach
    from apps.intelligence.models import Insight

    with tenant_scope(tenant):
        today = date.today()
        _card(
            name="Store card",
            balance=600_000,
            apr="24",
            promotional_apr="0",
            promotional_apr_until=today + timedelta(days=20),
            opened_on=today - timedelta(days=300),
        )
        coach.generate_insights()

        promo = Insight.objects.filter(kind="promo_expiry").first()
        assert promo is not None
        assert promo.rationale
        assert promo.evidence["standard_apr"] == 24.0


# =============================================================================
# Analytics and export
# =============================================================================
def test_analytics_series_reconcile_with_the_plan(tenant):
    """Every series is a view of one simulation — running the simulator per
    chart would be slower and able to disagree with itself."""
    with tenant_scope(tenant):
        _card(name="Card", balance=600_000, apr="18", minimum=30_000)

        data = debt_selectors.debt_analytics(months=12)
        assert data is not None
        assert data["series"], "expected a monthly series"

        first = data["series"][0]
        # Payment splits three ways and nothing is unaccounted for.
        assert first["interest_minor"] > 0
        assert first["principal_minor"] > 0
        assert data["monthly_velocity_minor"] == first["principal_minor"]


def test_analytics_cumulative_series_only_grows(tenant):
    with tenant_scope(tenant):
        _card(balance=600_000, apr="18", minimum=30_000)
        series = debt_selectors.debt_analytics(months=12)["series"]

        cumulative = [row["cumulative_interest_minor"] for row in series]
        assert cumulative == sorted(cumulative)


def test_analytics_composition_sums_to_a_hundred_percent(tenant):
    with tenant_scope(tenant):
        _card(name="Card", balance=400_000, apr="20", minimum=20_000)
        loan = finance_services.create_financial_account(
            name="Car loan",
            account_type=AccountType.LOAN,
            currency="USD",
            opening_balance_minor=600_000,
        )
        debt_services.set_debt_terms(
            financial_account=loan,
            apr="6",
            minimum_payment_minor=20_000,
            debt_kind=DebtKind.VEHICLE_LOAN,
        )

        composition = debt_selectors.debt_analytics()["composition"]
        assert round(sum(row["percent"] for row in composition)) == 100


def test_analytics_is_none_without_plannable_debt(tenant):
    with tenant_scope(tenant):
        assert debt_selectors.debt_analytics() is None


def test_csv_export_uses_major_units(tenant):
    """A column of minor-unit integers is a trap for anyone who sums it."""
    with tenant_scope(tenant):
        _card(name="Card", balance=60_000, apr="0", minimum=20_000)

        csv_text = debt_selectors.payoff_timeline_csv()
        lines = csv_text.strip().splitlines()
        assert lines[0].startswith("month,date,debt,")
        # 200.00, not 20000.
        assert ",200.00," in lines[1]
        assert len(lines) == 4  # header + three months


def test_csv_export_marks_the_clearing_month(tenant):
    with tenant_scope(tenant):
        _card(name="Card", balance=40_000, apr="0", minimum=20_000)
        csv_text = debt_selectors.payoff_timeline_csv()
        assert csv_text.strip().splitlines()[-1].endswith("yes,USD")


def test_csv_export_is_empty_without_debt(tenant):
    with tenant_scope(tenant):
        assert debt_selectors.payoff_timeline_csv() == ""


def test_api_analytics_and_export(tenant_context):
    _, client = tenant_context
    _api_card(client, balance=600_000, apr="18", minimum=30_000)

    analytics = client.get("/api/v1/debt/debts/analytics/?months=12")
    assert analytics.status_code == 200, analytics.data
    assert analytics.data["series"]
    assert analytics.data["composition"]

    export = client.get("/api/v1/debt/debts/payoff/export/")
    assert export.status_code == 200
    assert export["Content-Type"] == "text/csv"
    assert "attachment" in export["Content-Disposition"]


def test_api_analytics_is_204_without_debt(tenant_context):
    _, client = tenant_context
    assert client.get("/api/v1/debt/debts/analytics/").status_code == 204


def test_debt_alerts_include_the_signal_engine(tenant_context):
    """The dashboard and the coach read the same analysis, so they can't
    disagree about the same debt."""
    _, client = tenant_context
    account = client.post(
        "/api/v1/finance/accounts/",
        {
            "name": "Store card",
            "account_type": "credit_card",
            "currency": "USD",
            "opening_balance_minor": 600_000,
        },
        format="json",
    ).data
    client.put(
        f"/api/v1/debt/debts/{account['id']}/terms/",
        {
            "apr": "24",
            "minimum_payment_minor": 30_000,
            "debt_kind": "credit_card",
            "promotional_apr": "0",
            "promotional_apr_until": (date.today() + timedelta(days=20)).isoformat(),
            "opened_on": (date.today() - timedelta(days=300)).isoformat(),
        },
        format="json",
    )

    alerts = client.get("/api/v1/debt/debts/summary/").data["alerts"]
    assert any("promotional rate ends" in a["title"] for a in alerts)


def test_pdf_export_produces_a_real_document(tenant):
    with tenant_scope(tenant):
        _card(name="Card", balance=600_000, apr="18", minimum=30_000)
        pdf = debt_selectors.payoff_timeline_pdf()

        # A real PDF, not an empty buffer or an HTML error page.
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 1_000


def test_pdf_export_is_empty_without_debt(tenant):
    with tenant_scope(tenant):
        # Empty rather than a blank document, so callers can answer 204.
        assert debt_selectors.payoff_timeline_pdf() == b""


def test_pdf_export_handles_a_plan_that_never_clears(tenant):
    """The impossible case must render, not raise — that user most needs the
    document."""
    with tenant_scope(tenant):
        _card(name="Underwater", balance=500_000, apr="24", minimum=5_000)
        pdf = debt_selectors.payoff_timeline_pdf()
        assert pdf.startswith(b"%PDF")


def test_api_pdf_export(tenant_context):
    _, client = tenant_context
    _api_card(client, balance=600_000, apr="18", minimum=30_000)

    resp = client.get("/api/v1/debt/debts/payoff/export.pdf")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert "attachment" in resp["Content-Disposition"]
    assert resp.content.startswith(b"%PDF")


def test_api_pdf_is_204_without_debt(tenant_context):
    _, client = tenant_context
    assert client.get("/api/v1/debt/debts/payoff/export.pdf").status_code == 204
