"""Pure arithmetic for the income stop scenario — no database, no HTTP."""

from apps.income.stress import if_source_stops, snapshot


def test_snapshot_is_none_percent_without_income():
    snap = snapshot(monthly_income_minor=0, monthly_fixed_minor=0, committed_minor=80_000)
    assert snap.committed_pct is None
    assert snap.shortfall_minor == 80_000
    assert snap.free_minor == -80_000


def test_stopping_a_side_stream_raises_the_committed_share():
    scenario = if_source_stops(
        source_id="s1",
        source_name="Side gig",
        dropped_monthly_minor=100_000,
        currency="USD",
        monthly_income_minor=500_000,
        monthly_fixed_minor=400_000,
        committed_minor=300_000,
        source_is_fixed=False,
    )
    assert scenario.before.committed_pct == 60.0
    assert scenario.after.monthly_income_minor == 400_000
    assert scenario.after.committed_pct == 75.0
    assert scenario.after.monthly_fixed_minor == 400_000
    assert "75%" in scenario.sentence


def test_stopping_fixed_pay_also_shrinks_the_fixed_denominator():
    scenario = if_source_stops(
        source_id="s1",
        source_name="Salary",
        dropped_monthly_minor=400_000,
        currency="USD",
        monthly_income_minor=500_000,
        monthly_fixed_minor=400_000,
        committed_minor=300_000,
        source_is_fixed=True,
    )
    assert scenario.after.monthly_fixed_minor == 0
    assert scenario.after.monthly_income_minor == 100_000
    assert scenario.after.shortfall_minor == 200_000
    assert "shortfall" in scenario.sentence


def test_stopping_the_only_stream_leaves_no_denominator():
    scenario = if_source_stops(
        source_id="s1",
        source_name="Salary",
        dropped_monthly_minor=300_000,
        currency="KES",
        monthly_income_minor=300_000,
        monthly_fixed_minor=300_000,
        committed_minor=120_000,
        source_is_fixed=True,
    )
    assert scenario.after.monthly_income_minor == 0
    assert scenario.after.committed_pct is None
    assert "no remaining income" in scenario.sentence
