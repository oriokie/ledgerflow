"""Financial goals: taxonomy, forecasting engine, auto-contribution, and the
recommendation engine.

The forecasting tests deliberately pin the *refusals* as hard as the answers.
A forecast that invents a completion date, or a probability built from two data
points, is worse than no forecast — it looks like knowledge. Several tests exist
solely to assert that the engine returns `None`.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from apps.finance import services as finance_services
from apps.finance.models import AccountType
from apps.goals import forecasting, recommendations
from apps.goals import services as goal_services
from apps.goals.models import GoalKind, GoalPriority, GoalStatus, GoalTracking
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db

TODAY = date(2026, 6, 15)


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _goal(**overrides):
    params = {
        "name": "Trip to Japan",
        "currency": "USD",
        "target_minor": 6_000_00,
        "target_date": date(2027, 6, 1),
    }
    params.update(overrides)
    return goal_services.create_goal(**params)


def _fund(goal, months: list[tuple[date, int]]):
    for occurred_on, amount in months:
        goal_services.add_contribution(goal=goal, amount_minor=amount, occurred_on=occurred_on)


# --------------------------------------------------------------------- taxonomy
def test_goal_kinds_cover_the_supported_taxonomy():
    assert {
        GoalKind.EMERGENCY_FUND,
        GoalKind.VACATION,
        GoalKind.HOUSE_DEPOSIT,
        GoalKind.EDUCATION,
        GoalKind.RETIREMENT,
        GoalKind.VEHICLE,
        GoalKind.DEBT_PAYOFF,
        GoalKind.CUSTOM,
    } <= set(GoalKind.values)


def test_priority_defaults_from_kind_but_is_overridable(tenant):
    with tenant_scope(tenant):
        safety = _goal(name="Safety net", kind=GoalKind.EMERGENCY_FUND)
        holiday = _goal(name="Holiday", kind=GoalKind.VACATION)
        forced = _goal(name="Forced", kind=GoalKind.VACATION, priority=GoalPriority.CRITICAL)

        # A safety net outranks a holiday unless the user says otherwise.
        assert safety.priority == GoalPriority.CRITICAL
        assert holiday.priority == GoalPriority.LOW
        assert forced.priority == GoalPriority.CRITICAL


# ------------------------------------------------------------ month arithmetic
def test_add_months_clamps_to_the_end_of_short_months():
    # Naive month addition here produces 3 March, which silently drifts every
    # forecast that crosses a short month.
    assert forecasting.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert forecasting.add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)  # leap
    assert forecasting.add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)
    assert forecasting.add_months(date(2026, 3, 15), -3) == date(2025, 12, 15)


def test_months_between_is_signed():
    assert forecasting.months_between(date(2026, 1, 1), date(2026, 7, 1)) == 6
    assert forecasting.months_between(date(2026, 7, 1), date(2026, 1, 1)) == -6


# ------------------------------------------------------- required contribution
def test_required_monthly_rounds_up_so_the_target_is_actually_reached(tenant):
    with tenant_scope(tenant):
        goal = _goal(target_minor=1_000_00, target_date=date(2026, 9, 15))
        # 3 months, 100000 minor: 33333.33 -> must round UP or you finish short.
        assert forecasting.required_monthly_minor(goal, as_of=TODAY) == 33334


def test_required_monthly_is_none_without_a_deadline_or_when_met(tenant):
    with tenant_scope(tenant):
        undated = _goal(target_date=None)
        assert forecasting.required_monthly_minor(undated, as_of=TODAY) is None

        met = _goal(name="Done", target_minor=100_00)
        _fund(met, [(date(2026, 5, 1), 100_00)])
        assert forecasting.required_monthly_minor(met, as_of=TODAY) is None


def test_required_monthly_is_none_once_the_deadline_has_passed(tenant):
    with tenant_scope(tenant):
        overdue = _goal(name="Overdue", target_date=date(2026, 1, 1))
        assert forecasting.required_monthly_minor(overdue, as_of=TODAY) is None


# ------------------------------------------------------------- observed rate
def test_observed_rate_averages_across_the_window_including_empty_months(tenant):
    with tenant_scope(tenant):
        goal = _goal()
        # Two funded months inside a six-month window.
        _fund(goal, [(date(2026, 5, 10), 300_00), (date(2026, 6, 10), 300_00)])
        # 60000 over 6 months, not over the 2 that had activity — a goal funded
        # twice in six months is not a 300/month habit.
        assert forecasting.observed_monthly_rate_minor(goal, as_of=TODAY) == 100_00


def test_observed_rate_is_none_without_history(tenant):
    with tenant_scope(tenant):
        goal = _goal()
        # Not zero: zero is a claim, None is "not known yet".
        assert forecasting.observed_monthly_rate_minor(goal, as_of=TODAY) is None


def test_consistency_distinguishes_a_habit_from_a_one_off(tenant):
    with tenant_scope(tenant):
        habit = _goal(name="Habit")
        _fund(habit, [(date(2026, m, 5), 100_00) for m in range(1, 7)])
        one_off = _goal(name="One off")
        _fund(one_off, [(date(2026, 6, 5), 600_00)])

        # Same total, very different signal.
        assert forecasting.contribution_consistency(habit, as_of=TODAY) == 1.0
        assert forecasting.contribution_consistency(one_off, as_of=TODAY) < 0.2


# ------------------------------------------------------------------- forecast
def test_projected_completion_uses_observed_pace(tenant):
    with tenant_scope(tenant):
        goal = _goal(target_minor=1_200_00)
        _fund(goal, [(date(2026, m, 5), 100_00) for m in range(1, 7)])
        # 600 saved, 600 remaining, running at 100/month -> 6 months out.
        assert forecasting.projected_completion_date(goal, as_of=TODAY) == date(2026, 12, 15)


def test_projection_falls_back_to_the_plan_when_there_is_no_history(tenant):
    with tenant_scope(tenant):
        goal = _goal(target_minor=1_200_00, planned_monthly_minor=200_00)
        assert forecasting.projected_completion_date(goal, as_of=TODAY) == date(2026, 12, 15)


def test_projection_is_none_when_nothing_supports_one(tenant):
    with tenant_scope(tenant):
        goal = _goal()  # no history, no plan
        assert forecasting.projected_completion_date(goal, as_of=TODAY) is None


def test_absurdly_distant_projections_are_refused(tenant):
    with tenant_scope(tenant):
        # 1 minor unit a month against a large target: mathematically a date,
        # practically meaningless. Better to say nothing.
        goal = _goal(target_minor=10_000_00, planned_monthly_minor=1)
        assert forecasting.projected_completion_date(goal, as_of=TODAY) is None


def test_forecast_reports_the_shortfall_between_pace_and_requirement(tenant):
    with tenant_scope(tenant):
        goal = _goal(target_minor=6_000_00, target_date=date(2027, 6, 1))
        _fund(goal, [(date(2026, m, 5), 100_00) for m in range(1, 7)])

        f = forecasting.forecast(goal, as_of=TODAY)
        assert f.saved_minor == 600_00
        assert f.remaining_minor == 5_400_00
        assert f.observed_monthly_minor == 100_00
        assert f.required_monthly_minor == 45_000  # 5400.00 over 12 months
        assert f.monthly_shortfall_minor == 35_000
        assert f.on_track is False


def test_forecast_marks_a_met_goal_on_track(tenant):
    with tenant_scope(tenant):
        goal = _goal(target_minor=100_00)
        _fund(goal, [(date(2026, 6, 1), 150_00)])
        f = forecasting.forecast(goal, as_of=TODAY)
        assert f.remaining_minor == 0
        assert f.on_track is True
        assert f.percent == 100.0


def test_projection_series_flattens_at_the_target(tenant):
    with tenant_scope(tenant):
        goal = _goal(target_minor=500_00, planned_monthly_minor=200_00)
        series = forecasting.projection_series(goal, as_of=TODAY, horizon_months=12)

        assert series, "a goal with a plan should project"
        # Never projects past the target.
        assert all(p.projected_minor <= goal.target_minor for p in series)
        assert series[-1].projected_minor == goal.target_minor


def test_projection_series_is_empty_without_a_basis(tenant):
    with tenant_scope(tenant):
        goal = _goal()
        # A flat line at today's balance would imply a prediction we don't have.
        assert forecasting.projection_series(goal, as_of=TODAY) == []


# -------------------------------------------------------- success probability
def test_probability_is_none_without_enough_history(tenant):
    with tenant_scope(tenant):
        goal = _goal()
        _fund(goal, [(date(2026, 5, 5), 100_00), (date(2026, 6, 5), 100_00)])
        # Two funded months is noise. Refusing to answer is the point.
        assert forecasting.success_probability(goal, as_of=TODAY) is None


def test_probability_is_none_without_a_deadline(tenant):
    with tenant_scope(tenant):
        goal = _goal(target_date=None)
        _fund(goal, [(date(2026, m, 5), 100_00) for m in range(1, 7)])
        assert forecasting.success_probability(goal, as_of=TODAY) is None


def test_probability_is_one_for_an_already_met_goal(tenant):
    with tenant_scope(tenant):
        goal = _goal(target_minor=100_00)
        _fund(goal, [(date(2026, 6, 5), 100_00)])
        assert forecasting.success_probability(goal, as_of=TODAY) == 1.0


def test_probability_rises_with_pace(tenant):
    with tenant_scope(tenant):
        behind = _goal(name="Behind", target_minor=12_000_00, target_date=date(2027, 6, 1))
        _fund(behind, [(date(2026, m, 5), 50_00) for m in range(1, 7)])

        ahead = _goal(name="Ahead", target_minor=1_200_00, target_date=date(2027, 6, 1))
        _fund(ahead, [(date(2026, m, 5), 200_00) for m in range(1, 7)])

        p_behind = forecasting.success_probability(behind, as_of=TODAY)
        p_ahead = forecasting.success_probability(ahead, as_of=TODAY)
        assert p_behind is not None and p_ahead is not None
        assert p_ahead > p_behind
        assert 0.0 <= p_behind <= 1.0 and 0.0 <= p_ahead <= 1.0


def test_erratic_saving_scores_below_steady_saving_at_the_same_mean(tenant):
    with tenant_scope(tenant):
        steady = _goal(name="Steady", target_minor=3_600_00, target_date=date(2027, 6, 1))
        _fund(steady, [(date(2026, m, 5), 100_00) for m in range(1, 7)])

        erratic = _goal(name="Erratic", target_minor=3_600_00, target_date=date(2027, 6, 1))
        _fund(erratic, [(date(2026, 4, 5), 200_00), (date(2026, 5, 5), 200_00), (date(2026, 6, 5), 200_00)])

        p_steady = forecasting.success_probability(steady, as_of=TODAY)
        p_erratic = forecasting.success_probability(erratic, as_of=TODAY)
        # Same 600 total; the habit is the stronger signal.
        assert p_steady is not None and p_erratic is not None
        assert p_steady > p_erratic


# ------------------------------------------------------------ auto contribution
def test_auto_contribution_requires_a_valid_amount_and_day(tenant):
    with tenant_scope(tenant):
        goal = _goal()
        with pytest.raises(goal_services.GoalError):
            goal_services.set_auto_contribution(goal=goal, enabled=True, amount_minor=0, day_of_month=1)
        with pytest.raises(goal_services.GoalError):
            # Day 31 doesn't exist in every month; capping at 28 is deliberate.
            goal_services.set_auto_contribution(goal=goal, enabled=True, amount_minor=100_00, day_of_month=31)


def test_auto_contribution_rejects_account_balance_goals(tenant):
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Savings", account_type=AccountType.SAVINGS, currency="USD"
        )
        goal = _goal(tracking=GoalTracking.ACCOUNT_BALANCE, linked_account=account)
        with pytest.raises(goal_services.GoalError):
            goal_services.set_auto_contribution(goal=goal, enabled=True, amount_minor=100_00, day_of_month=1)


def test_auto_contribution_runs_once_per_month(tenant):
    with tenant_scope(tenant):
        goal = _goal()
        goal_services.set_auto_contribution(goal=goal, enabled=True, amount_minor=250_00, day_of_month=10)

        assert goal_services.run_due_auto_contributions(as_of=TODAY) == 1
        # Re-running the same month must never double-fund.
        assert goal_services.run_due_auto_contributions(as_of=TODAY) == 0
        assert goal_services.run_due_auto_contributions(as_of=date(2026, 6, 28)) == 0

        goal.refresh_from_db()
        assert forecasting.forecast(goal, as_of=TODAY).saved_minor == 250_00

        # Next month it fires again.
        assert goal_services.run_due_auto_contributions(as_of=date(2026, 7, 12)) == 1


def test_auto_contribution_does_not_run_before_its_day(tenant):
    with tenant_scope(tenant):
        goal = _goal()
        goal_services.set_auto_contribution(goal=goal, enabled=True, amount_minor=100_00, day_of_month=20)
        assert goal_services.run_due_auto_contributions(as_of=TODAY) == 0


def test_disabling_auto_contribution_clears_the_rule(tenant):
    with tenant_scope(tenant):
        goal = _goal()
        goal_services.set_auto_contribution(goal=goal, enabled=True, amount_minor=100_00, day_of_month=5)
        goal_services.set_auto_contribution(goal=goal, enabled=False)
        goal.refresh_from_db()
        assert goal.auto_contribute_enabled is False
        assert goal.auto_contribute_minor is None
        assert goal_services.run_due_auto_contributions(as_of=TODAY) == 0


# ------------------------------------------------------------------- updates
def test_update_changes_the_plan_but_not_currency_or_tracking(tenant):
    with tenant_scope(tenant):
        goal = _goal()
        goal_services.update_goal(
            goal=goal,
            name="Japan 2027",
            priority=GoalPriority.HIGH,
            planned_monthly_minor=400_00,
            currency="EUR",
            tracking=GoalTracking.ACCOUNT_BALANCE,
        )
        goal.refresh_from_db()
        assert goal.name == "Japan 2027"
        assert goal.priority == GoalPriority.HIGH
        assert goal.planned_monthly_minor == 400_00
        # Both would reinterpret every contribution already recorded.
        assert goal.currency == "USD"
        assert goal.tracking == GoalTracking.MANUAL


def test_lowering_the_target_below_progress_marks_the_goal_achieved(tenant):
    with tenant_scope(tenant):
        goal = _goal(target_minor=1_000_00)
        _fund(goal, [(date(2026, 6, 1), 500_00)])
        goal_services.update_goal(goal=goal, target_minor=400_00)
        goal.refresh_from_db()
        assert goal.status == GoalStatus.ACHIEVED


# ----------------------------------------------------------- recommendations
def test_no_recommendations_without_enough_history(tenant):
    with tenant_scope(tenant):
        # An empty workspace can't support an honest suggestion, and filler
        # would cost credibility.
        assert recommendations.recommend_goals() == []


def test_debt_payoff_is_recommended_when_a_card_carries_a_balance(tenant):
    with tenant_scope(tenant):
        finance_services.create_financial_account(
            name="Card",
            account_type=AccountType.CREDIT_CARD,
            currency="USD",
            opening_balance_minor=2_400_00,
        )
        recs = recommendations.recommend_goals()
        debt = [r for r in recs if r.kind == GoalKind.DEBT_PAYOFF]
        assert len(debt) == 1
        # Sized to what is actually owed, not a generic figure.
        assert debt[0].suggested_target_minor == 2_400_00


def test_recommendations_never_duplicate_an_existing_goal(tenant):
    with tenant_scope(tenant):
        finance_services.create_financial_account(
            name="Card",
            account_type=AccountType.CREDIT_CARD,
            currency="USD",
            opening_balance_minor=2_400_00,
        )
        assert any(r.kind == GoalKind.DEBT_PAYOFF for r in recommendations.recommend_goals())

        _goal(name="Clear the card", kind=GoalKind.DEBT_PAYOFF, target_minor=2_400_00)
        # Nagging about a goal the user already set is how software loses trust.
        assert not any(r.kind == GoalKind.DEBT_PAYOFF for r in recommendations.recommend_goals())


# ------------------------------------------------------------------- tasks
def test_auto_contribution_task_is_safe_to_run_repeatedly(tenant):
    """The beat sweep runs daily, so the per-tenant task must be idempotent —
    a worker retry or a catch-up after an outage cannot double-fund a goal."""
    from apps.goals.tasks import run_auto_contributions_for_tenant

    with tenant_scope(tenant):
        goal = _goal()
        goal_services.set_auto_contribution(goal=goal, enabled=True, amount_minor=100_00, day_of_month=1)

    first = run_auto_contributions_for_tenant(str(tenant))
    second = run_auto_contributions_for_tenant(str(tenant))

    assert first == 1
    assert second == 0

    with tenant_scope(tenant):
        goal.refresh_from_db()
        assert forecasting.forecast(goal).saved_minor == 100_00
