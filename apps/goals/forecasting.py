"""Goal forecasting — when will this goal actually be met, and how likely is it?

Everything here is derived on read from contribution history and the goal's own
plan. Nothing is stored, for the same reason budget progress isn't stored: a
cached forecast is a forecast that silently goes stale.

Three different "monthly amounts" exist and are deliberately kept apart, because
conflating them is what makes goal forecasts useless:

    required  — what you must contribute to hit the target by the target date.
                Pure arithmetic from remaining amount and months left.
    planned   — what the user said they intend to contribute.
    observed  — what they have actually been contributing, measured from
                history.

A forecast that only knows `required` can tell you the plan; only one that also
knows `observed` can tell you the truth.

On success probability: this module returns `None` rather than a number when
there is not enough history to say anything defensible. A probability invented
from two data points is worse than no probability at all — it looks like
knowledge. See `success_probability` for the model and its stated limits.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import GoalContribution, GoalStatus, GoalTracking, SavingsGoal
from .selectors import goal_progress_minor

#: Months of history used to measure the observed contribution rate. Long
#: enough to smooth a skipped month, short enough to follow a real change in
#: circumstances.
RUN_RATE_WINDOW_MONTHS = 6

#: Below this many months with any contribution, the observed rate is noise and
#: no probability is reported.
MIN_MONTHS_FOR_PROBABILITY = 3

#: Forecasts beyond this horizon are not meaningful for personal finance and
#: are reported as "not on this trajectory" instead of a date in 2190.
MAX_FORECAST_MONTHS = 600  # 50 years


def months_between(start: date, end: date) -> int:
    """Whole calendar months from `start` to `end`. Negative if end precedes start."""
    return (end.year - start.year) * 12 + (end.month - start.month)


def add_months(anchor: date, months: int) -> date:
    """Calendar-safe month addition, clamping the day to the target month.

    Adding one month to 31 January yields 28/29 February, not an error and not
    3 March. Anything else produces forecast dates that drift.
    """
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    # Last day of the target month, without importing calendar arithmetic.
    if month == 12:  # noqa: SIM108 — the ternary reads worse than this
        last_day = 31
    else:
        last_day = (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(anchor.day, last_day))


@dataclass(frozen=True, slots=True)
class MonthlyContribution:
    month: date  # first of month
    amount_minor: int


def monthly_contribution_history(
    goal: SavingsGoal, *, months: int = RUN_RATE_WINDOW_MONTHS, as_of: date | None = None
) -> list[MonthlyContribution]:
    """Contributions bucketed by calendar month, oldest first.

    Months with no contribution are returned explicitly as zero. That matters:
    a goal funded once in six months has a very different run rate from one
    funded every month, and dropping the empty months would hide the
    difference.
    """
    as_of = as_of or timezone.localdate()
    window_start = add_months(as_of.replace(day=1), -(months - 1))

    rows = (
        GoalContribution.objects.filter(goal=goal, occurred_on__gte=window_start)
        .annotate(bucket=TruncMonth("occurred_on"))
        .values("bucket")
        .annotate(total=Sum("amount_minor"))
    )
    by_month = {r["bucket"]: r["total"] or 0 for r in rows}

    out: list[MonthlyContribution] = []
    for i in range(months):
        m = add_months(window_start, i)
        out.append(MonthlyContribution(month=m, amount_minor=by_month.get(m, 0)))
    return out


def observed_monthly_rate_minor(goal: SavingsGoal, *, as_of: date | None = None) -> int | None:
    """Mean monthly contribution over the recent window.

    `None` when the goal has no contribution history at all — an account-balance
    goal, or one that has never been funded. Returning 0 would be a claim ("you
    contribute nothing"); `None` is the honest "not known yet".
    """
    if goal.tracking != GoalTracking.MANUAL:
        return None
    history = monthly_contribution_history(goal, as_of=as_of)
    if not any(h.amount_minor for h in history):
        return None
    return sum(h.amount_minor for h in history) // len(history)


def contribution_consistency(goal: SavingsGoal, *, as_of: date | None = None) -> float:
    """Fraction of recent months that received any contribution, 0.0–1.0.

    A goal funded in 6 of 6 months is a habit; one funded in 2 of 6 is an
    intention. Both can share a mean, which is why the mean alone is not enough
    to judge whether a plan will hold.
    """
    history = monthly_contribution_history(goal, as_of=as_of)
    if not history:
        return 0.0
    funded = sum(1 for h in history if h.amount_minor > 0)
    return funded / len(history)


def required_monthly_minor(
    goal: SavingsGoal, *, saved_minor: int | None = None, as_of: date | None = None
) -> int | None:
    """Contribution needed each month to hit the target by `target_date`.

    `None` when the goal has no target date (nothing to solve for), is already
    met, or the date has passed.
    """
    if goal.target_date is None:
        return None
    saved = goal_progress_minor(goal) if saved_minor is None else saved_minor
    remaining = max(0, goal.target_minor - saved)
    if remaining == 0:
        return None
    as_of = as_of or timezone.localdate()
    months = months_between(as_of, goal.target_date)
    if months <= 0:
        return None
    return -(-remaining // months)  # ceil division: never under-state the ask


def success_probability(
    goal: SavingsGoal, *, saved_minor: int | None = None, as_of: date | None = None
) -> float | None:
    """Likelihood of hitting the target by the target date, 0.0–1.0.

    **This is a calibrated heuristic, not a statistical guarantee**, and it is
    labelled as such everywhere it surfaces. The model:

        ratio       = observed monthly rate ÷ required monthly rate
        base        = logistic(4 × (ratio − 1))   → 0.5 at exactly on-pace
        probability = base × (0.6 + 0.4 × consistency)

    The logistic gives a smooth, saturating response: contributing twice the
    required amount is reassuring but not a certainty, and contributing half is
    discouraging but not impossible. The consistency term caps an erratic
    saver's score, because a mean built from one large deposit is a weaker
    signal than the same mean built from six regular ones.

    Returns `None` — never a number — when:
      * there is no target date (nothing to be on time for);
      * fewer than `MIN_MONTHS_FOR_PROBABILITY` months have any contribution;
      * the goal is not manually tracked, so no contribution history exists.

    Refusing to answer is the point. A probability fabricated from thin data
    would look exactly like one earned from rich data.
    """
    if goal.target_date is None:
        return None

    saved = goal_progress_minor(goal) if saved_minor is None else saved_minor
    if saved >= goal.target_minor:
        return 1.0

    history = monthly_contribution_history(goal, as_of=as_of)
    funded_months = sum(1 for h in history if h.amount_minor > 0)
    if funded_months < MIN_MONTHS_FOR_PROBABILITY:
        return None

    observed = observed_monthly_rate_minor(goal, as_of=as_of)
    required = required_monthly_minor(goal, saved_minor=saved, as_of=as_of)
    if observed is None:
        return None
    if required is None:
        # Target date already passed and the goal is unmet.
        return 0.0

    ratio = observed / required
    base = 1 / (1 + math.exp(-4 * (ratio - 1)))
    consistency = contribution_consistency(goal, as_of=as_of)
    return round(min(1.0, max(0.0, base * (0.6 + 0.4 * consistency))), 3)


def projected_completion_date(
    goal: SavingsGoal, *, saved_minor: int | None = None, as_of: date | None = None
) -> date | None:
    """When the goal is met if current behaviour continues.

    Uses the observed rate where there's history, falling back to the planned
    monthly amount. `None` when neither exists, or when the trajectory would
    take longer than `MAX_FORECAST_MONTHS` — a completion date half a century
    out is not information, it's noise dressed as precision.
    """
    saved = goal_progress_minor(goal) if saved_minor is None else saved_minor
    remaining = max(0, goal.target_minor - saved)
    as_of = as_of or timezone.localdate()
    if remaining == 0:
        return as_of

    rate = observed_monthly_rate_minor(goal, as_of=as_of) or goal.planned_monthly_minor
    if not rate or rate <= 0:
        return None

    months = -(-remaining // rate)  # ceil
    if months > MAX_FORECAST_MONTHS:
        return None
    return add_months(as_of, months)


@dataclass(frozen=True, slots=True)
class ProjectionPoint:
    month: date
    projected_minor: int
    target_minor: int


def projection_series(
    goal: SavingsGoal,
    *,
    saved_minor: int | None = None,
    as_of: date | None = None,
    horizon_months: int = 24,
) -> list[ProjectionPoint]:
    """Month-by-month projected balance, for the goal projection chart.

    Starts at today's actual progress and extends at the observed (or planned)
    rate, clamped at the target so the curve flattens on completion rather than
    running past it. Empty when there is no rate to project from — a chart of a
    flat line at today's balance implies a prediction we haven't got.
    """
    saved = goal_progress_minor(goal) if saved_minor is None else saved_minor
    as_of = as_of or timezone.localdate()
    rate = observed_monthly_rate_minor(goal, as_of=as_of) or goal.planned_monthly_minor
    if not rate or rate <= 0:
        return []

    points: list[ProjectionPoint] = []
    running = saved
    for i in range(horizon_months + 1):
        points.append(
            ProjectionPoint(
                month=add_months(as_of.replace(day=1), i),
                projected_minor=min(running, goal.target_minor),
                target_minor=goal.target_minor,
            )
        )
        if running >= goal.target_minor:
            break
        running += rate
    return points


@dataclass(frozen=True, slots=True)
class GoalForecast:
    """Everything the UI needs to explain where a goal stands and where it's going."""

    goal_id: str
    currency: str
    saved_minor: int
    target_minor: int
    remaining_minor: int
    percent: float
    required_monthly_minor: int | None
    planned_monthly_minor: int | None
    observed_monthly_minor: int | None
    monthly_shortfall_minor: int | None
    projected_completion: date | None
    target_date: date | None
    on_track: bool | None
    success_probability: float | None
    consistency: float


def forecast(goal: SavingsGoal, *, as_of: date | None = None) -> GoalForecast:
    """The full forecast for one goal. One call, one pass over its history."""
    as_of = as_of or timezone.localdate()
    saved = goal_progress_minor(goal)
    remaining = max(0, goal.target_minor - saved)
    required = required_monthly_minor(goal, saved_minor=saved, as_of=as_of)
    observed = observed_monthly_rate_minor(goal, as_of=as_of)
    projected = projected_completion_date(goal, saved_minor=saved, as_of=as_of)

    # Shortfall compares what's needed against the best evidence of what's
    # happening: observed behaviour if known, otherwise the stated plan.
    effective = observed if observed is not None else goal.planned_monthly_minor
    shortfall = None
    if required is not None and effective is not None:
        shortfall = max(0, required - effective)

    # "On track" is only answerable with both a deadline and a projection.
    on_track: bool | None = None
    if saved >= goal.target_minor:
        on_track = True
    elif goal.target_date is not None and projected is not None:
        on_track = projected <= goal.target_date

    return GoalForecast(
        goal_id=str(goal.id),
        currency=goal.currency,
        saved_minor=saved,
        target_minor=goal.target_minor,
        remaining_minor=remaining,
        percent=round(min(100.0, saved / goal.target_minor * 100), 1) if goal.target_minor else 0.0,
        required_monthly_minor=required,
        planned_monthly_minor=goal.planned_monthly_minor,
        observed_monthly_minor=observed,
        monthly_shortfall_minor=shortfall,
        projected_completion=projected,
        target_date=goal.target_date,
        on_track=on_track,
        success_probability=success_probability(goal, saved_minor=saved, as_of=as_of),
        consistency=round(contribution_consistency(goal, as_of=as_of), 2),
    )


def forecast_active_goals(*, as_of: date | None = None) -> list[GoalForecast]:
    """Forecasts for every live goal, in funding order (priority, then deadline)."""
    goals = (
        SavingsGoal.objects.filter(status__in=[GoalStatus.ACTIVE, GoalStatus.PAUSED])
        .select_related("linked_account")
        .order_by("priority", "target_date", "name")
    )
    return [forecast(g, as_of=as_of) for g in goals]
