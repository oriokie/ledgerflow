"""Monte Carlo, sensitivity and risk — the analysis layer, still database-free.

What these defend is mostly *honesty properties* rather than arithmetic ones:

* a seeded simulation is reproducible, or nobody can act on it or check it,
* the spread is real — a volatile world must produce a wider band than a calm
  one, or the simulation is decoration,
* sensitivity and the named what-ifs agree, because they share the machinery,
* resilience is the weakest factor and not the average, so a large balance
  cannot hide having no cash.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.projections import risk, sensitivity, simulation
from apps.projections.engine import (
    CompiledEvent,
    DebtPosition,
    FinancialPosition,
)

TODAY = date(2026, 1, 31)


def position(**kwargs) -> FinancialPosition:
    base = {
        "currency": "KES",
        "as_of": TODAY,
        "liquid_minor": 2_000_000,
        "investment_minor": 5_000_000,
        "other_assets_minor": 0,
        "monthly_net_income_minor": 500_000,
        "monthly_expenses_minor": 400_000,
    }
    base.update(kwargs)
    return FinancialPosition(**base)


FAST = simulation.SimulationSettings(trials=60, seed=7)


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------


def test_a_seeded_simulation_is_reproducible():
    """A simulation whose answer changes on refresh is one nobody can act on,
    and two runs of the same scenario would not be comparable."""
    a = simulation.simulate(position=position(), months=120, settings=FAST)
    b = simulation.simulate(position=position(), months=120, settings=FAST)
    assert a.closing_net_worth == b.closing_net_worth
    assert a.success_probability == b.success_probability


def test_a_different_seed_gives_a_different_draw():
    a = simulation.simulate(position=position(), months=120, settings=FAST)
    b = simulation.simulate(
        position=position(), months=120, settings=simulation.SimulationSettings(trials=60, seed=99)
    )
    assert a.closing_net_worth.p50 != b.closing_net_worth.p50


def test_each_trial_draws_from_its_own_index_not_a_shared_stream():
    """Trial *k* must depend only on the seed and its own index, so raising the
    trial count refines the estimate rather than moving every percentile — the
    property that lets someone add trials to check a result rather than to get
    a different one."""
    first = [simulation._trial_rng(3, 0).random() for _ in range(3)]
    assert len(set(first)) == 1, "the same (seed, trial) must give the same stream"
    assert simulation._trial_rng(3, 1).random() != simulation._trial_rng(3, 0).random()
    assert simulation._trial_rng(4, 0).random() != simulation._trial_rng(3, 0).random()


def test_reproducibility_survives_a_process_restart():
    """Seeded from a string, not `hash()`: tuple/str hashing is randomised per
    process unless PYTHONHASHSEED is pinned, which would have made every
    "reproducible" claim here false across restarts."""
    import subprocess
    import sys

    script = "import random;" "print(random.Random('3:0').random())"
    outputs = {
        subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=True
        ).stdout.strip()
        for _ in range(2)
    }
    assert len(outputs) == 1
    assert outputs.pop() == str(simulation._trial_rng(3, 0).random())


def test_percentiles_are_ordered():
    result = simulation.simulate(position=position(), months=120, settings=FAST)
    p = result.closing_net_worth
    assert p.p10 <= p.p25 <= p.p50 <= p.p75 <= p.p90


def test_a_more_volatile_world_produces_a_wider_band():
    """If volatility did not widen the spread, the simulation would be
    decoration rather than a risk model."""
    calm = simulation.simulate(
        position=position(),
        months=240,
        settings=simulation.SimulationSettings(trials=80, seed=11, return_volatility=0.02),
    )
    wild = simulation.simulate(
        position=position(),
        months=240,
        settings=simulation.SimulationSettings(trials=80, seed=11, return_volatility=0.30),
    )
    assert wild.closing_net_worth.spread > calm.closing_net_worth.spread


def test_a_household_that_cannot_cover_its_costs_mostly_fails():
    result = simulation.simulate(
        position=position(
            liquid_minor=100_000, monthly_net_income_minor=100_000, monthly_expenses_minor=500_000
        ),
        months=120,
        settings=FAST,
    )
    assert result.failure_probability > 0.9
    assert result.median_failure_month is not None


def test_a_comfortable_household_mostly_succeeds():
    result = simulation.simulate(
        position=position(liquid_minor=20_000_000, monthly_expenses_minor=100_000),
        months=120,
        settings=simulation.SimulationSettings(trials=60, seed=7, income_shock_probability=0.0),
    )
    assert result.success_probability > 0.9
    assert result.median_failure_month is None


def test_the_deterministic_line_is_returned_alongside_the_band():
    """ "Where the smooth assumption put you" is exactly what the spread is
    arguing with, so it travels in the same response."""
    result = simulation.simulate(position=position(), months=60, settings=FAST)
    assert result.deterministic is not None
    assert len(result.deterministic.points) == 60


def test_bands_are_sampled_not_emitted_per_month():
    result = simulation.simulate(position=position(), months=480, settings=FAST)
    assert 0 < len(result.bands) <= 61
    assert result.bands[0]["p10"] <= result.bands[0]["p90"]


def test_simulation_settings_are_validated():
    with pytest.raises(simulation.SimulationError, match="trials"):
        simulation.SimulationSettings(trials=0)
    with pytest.raises(simulation.SimulationError, match="trials"):
        simulation.SimulationSettings(trials=simulation.MAX_TRIALS + 1)
    with pytest.raises(simulation.SimulationError, match="volatility"):
        simulation.SimulationSettings(return_volatility=-1)
    with pytest.raises(simulation.SimulationError, match="fraction"):
        simulation.SimulationSettings(income_shock_probability=2)


def test_the_simulation_states_its_assumptions():
    result = simulation.simulate(position=position(), months=60, settings=FAST)
    assert result.assumptions
    assert any("reproducible" in a for a in result.assumptions)


def test_scenario_events_are_present_in_every_draw():
    """Each trial re-runs the real engine, so a scenario's events survive into
    the distribution rather than being approximated away."""
    spend = CompiledEvent(label="House deposit", start_month=2, one_off_cash_minor=-1_900_000)
    plain = simulation.simulate(position=position(), months=60, settings=FAST)
    with_event = simulation.simulate(position=position(), months=60, events=[spend], settings=FAST)
    assert with_event.trough.p50 < plain.trough.p50


# ---------------------------------------------------------------------------
# sensitivity
# ---------------------------------------------------------------------------


def test_sensitivity_ranks_the_load_bearing_assumption_first():
    result = sensitivity.analyse(position=position(), months=240)
    assert result.swings
    spreads = [s.spread_minor for s in result.swings]
    assert spreads == sorted(spreads, reverse=True)
    assert result.dominant is result.swings[0]


def test_every_lever_is_tested():
    result = sensitivity.analyse(position=position(), months=120)
    tested = {s.lever for s in result.swings}
    assert set(sensitivity.LEVERS) <= tested


def test_debt_rates_are_only_a_lever_when_there_is_debt():
    without = sensitivity.analyse(position=position(), months=120)
    assert "debt_rates" not in {s.lever for s in without.swings}
    assert any("nothing to act on" in n for n in without.notes)

    debt = DebtPosition(label="Loan", balance_minor=3_000_000, annual_rate=0.12, monthly_payment_minor=80_000)
    with_debt = sensitivity.analyse(position=position(debts=(debt,)), months=120)
    assert "debt_rates" in {s.lever for s in with_debt.swings}


def test_higher_inflation_is_worse_and_higher_returns_are_better():
    result = sensitivity.analyse(position=position(), months=240)
    by_lever = {s.lever: s for s in result.swings}
    assert by_lever["annual_inflation"].direction == "higher is worse"
    assert by_lever["annual_investment_return"].direction == "higher is better"


def test_sensitivity_admits_it_ignores_interaction():
    """A tornado implying independence would be a claim, and a wrong one."""
    result = sensitivity.analyse(position=position(), months=120)
    assert any("move together" in n for n in result.notes)


def test_a_named_what_if_agrees_with_its_tornado_bar():
    """They share the machinery, so the "what if inflation hits 10%" card and
    the inflation bar cannot disagree — this pins that."""
    months = 180
    tornado = sensitivity.analyse(position=position(), months=months)
    bar = next(s for s in tornado.swings if s.lever == "annual_inflation")
    card = sensitivity.what_if(position=position(), months=months, inflation=bar.high_value)
    assert card.changed_closing_minor == bar.high_closing_minor


def test_a_what_if_flags_a_shortfall_it_introduces():
    """ "Introduces" is load-bearing: a household whose baseline already runs out
    has not been harmed by the assumption, and saying so would misattribute the
    cause. Income here comfortably clears expenses at 5% inflation and does not
    at 20%."""
    comfortable = position(
        liquid_minor=500_000, monthly_net_income_minor=600_000, monthly_expenses_minor=400_000
    )
    baseline_ok = sensitivity.what_if(position=comfortable, months=120, inflation=0.05)
    assert not baseline_ok.introduces_shortfall

    result = sensitivity.what_if(position=comfortable, months=120, inflation=0.20)
    assert result.introduces_shortfall
    assert any("goes negative" in n for n in result.notes)


def test_a_baseline_that_already_fails_is_not_blamed_on_the_assumption():
    already_failing = position(
        liquid_minor=100_000, monthly_net_income_minor=100_000, monthly_expenses_minor=500_000
    )
    result = sensitivity.what_if(position=already_failing, months=120, inflation=0.20)
    assert not result.introduces_shortfall


def test_a_rate_rise_what_if_needs_no_assumption_change():
    debt = DebtPosition(label="Card", balance_minor=2_000_000, annual_rate=0.10, monthly_payment_minor=60_000)
    result = sensitivity.what_if(position=position(debts=(debt,)), months=120, rate_shift=0.05)
    assert result.changed_closing_minor < result.baseline_closing_minor


def test_a_what_if_with_nothing_changed_is_an_error():
    with pytest.raises(ValueError, match="at least one assumption"):
        sensitivity.what_if(position=position(), months=60)


# ---------------------------------------------------------------------------
# risk
# ---------------------------------------------------------------------------


def test_resilience_is_the_weakest_factor_not_the_average():
    """A large investment balance must not hide having no cash."""
    profile = risk.assess(
        position=position(liquid_minor=0, investment_minor=50_000_000, monthly_expenses_minor=400_000)
    )
    runway = next(f for f in profile.factors if f.key == "runway")
    assert runway.score == 0
    assert profile.resilience == 0
    assert profile.weakest is runway


def test_factors_are_ordered_weakest_first():
    profile = risk.assess(position=position())
    scores = [f.score for f in profile.factors]
    assert scores == sorted(scores)


def test_a_thin_runway_carries_a_remedy_and_a_healthy_one_does_not():
    thin = risk.assess(position=position(liquid_minor=100_000))
    assert next(f for f in thin.factors if f.key == "runway").remedy

    healthy = risk.assess(position=position(liquid_minor=10_000_000))
    assert not next(f for f in healthy.factors if f.key == "runway").remedy


def test_debt_service_is_measured_against_income():
    debt = DebtPosition(
        label="Loan", balance_minor=5_000_000, annual_rate=0.15, monthly_payment_minor=300_000
    )
    profile = risk.assess(position=position(debts=(debt,)))
    service = next(f for f in profile.factors if f.key == "debt_service")
    assert service.value == pytest.approx(0.6)
    assert service.score == 0


def test_income_concentration_is_omitted_rather_than_guessed():
    """Reporting "well diversified" for sources we never counted would be
    worse than silence."""
    profile = risk.assess(position=position())
    assert "income_concentration" not in {f.key for f in profile.factors}
    assert any("not measured here" in n for n in profile.notes)


def test_income_concentration_is_measured_when_sources_are_given():
    single = risk.assess(position=position(), income_sources=[500_000])
    concentrated = next(f for f in single.factors if f.key == "income_concentration")
    assert concentrated.value == pytest.approx(1.0)
    assert "all of it" in concentrated.detail

    spread = risk.assess(position=position(), income_sources=[200_000, 180_000, 120_000])
    assert next(f for f in spread.factors if f.key == "income_concentration").score > concentrated.score


def test_the_headline_names_the_exposure_that_would_bite_first():
    profile = risk.assess(position=position(liquid_minor=0))
    assert profile.weakest is not None
    assert profile.weakest.label in profile.headline


def test_debt_with_no_recorded_assets_scores_zero_leverage_but_says_why():
    debt = DebtPosition(label="Loan", balance_minor=1_000_000, annual_rate=0.1, monthly_payment_minor=30_000)
    profile = risk.assess(
        position=position(liquid_minor=0, investment_minor=0, other_assets_minor=0, debts=(debt,))
    )
    leverage = next(f for f in profile.factors if f.key == "leverage")
    assert leverage.score == 0
    assert "may show this is better" in leverage.remedy


def test_every_factor_scores_higher_is_safer():
    """Direction must match the existing health score, or the two contradict
    each other on the same screen."""
    safe = risk.assess(position=position(liquid_minor=20_000_000, investment_minor=0))
    exposed = risk.assess(position=position(liquid_minor=0, investment_minor=20_000_000))
    assert safe.resilience > exposed.resilience


def test_an_empty_position_is_reported_as_unmeasurable_not_as_healthy():
    profile = risk.assess(position=FinancialPosition(currency="KES", as_of=TODAY))
    assert profile.resilience == 0
    assert "Not enough recorded" in profile.headline
