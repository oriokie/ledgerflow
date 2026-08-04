"""Monte Carlo — the same projection, run a thousand times against luck.

The Phase 1 engine answers "where does this go if the assumptions hold". That
is a useful question and an incomplete one, because the assumptions do not
hold: a 7% average return is not 7% every year, it is some years of 24% and
some of −18%, and *the order they arrive in changes the answer*. A single
smooth line hides that entirely, and it hides it in the flattering direction.

So this module runs the projection repeatedly with sampled conditions and
reports the spread. What comes back is not a better forecast — it is an honest
one: a band, a probability, and a worst case somebody can plan around.

**Three rules keep it from becoming theatre.**

*Seeded, always.* A simulation whose answer changes on refresh is one nobody
can act on or check, and two runs of the same scenario must be comparable. The
seed is part of the request and part of the response.

*The bad years cluster.* Real returns are not independent draws — downturns
persist, and a projection sampling each year independently understates exactly
the risk people care about. Returns here carry mild autocorrelation, so a bad
year makes the next one likelier to be bad.

*The number reported is the probability of not running out, not the average
outcome.* An average is the least useful statistic in retirement planning: half
the point of the exercise is that you only get one life, and the mean of a
thousand is not a plan. Percentiles and a failure rate are.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field, replace

from .calculators import MAX_HORIZON_MONTHS
from .engine import (
    CompiledEvent,
    EconomicAssumptions,
    FinancialPosition,
    ProjectionResult,
    project,
)

#: Default trial count. A thousand is where the percentile estimates stop
#: moving materially between seeds for the horizons this product uses; ten
#: thousand costs ten times as much and moves the 10th percentile by less than
#: a rounding step in the currency.
DEFAULT_TRIALS = 1_000

#: Hard cap, because this runs inside a request. A 40-year, 5,000-trial run is
#: 2.4 million engine-months, which is not something to discover in production.
MAX_TRIALS = 5_000

#: Annual standard deviation of investment returns. Roughly the long-run figure
#: for a diversified equity-heavy portfolio; stated here so it can be argued
#: with rather than buried.
DEFAULT_RETURN_VOLATILITY = 0.15

#: Annual standard deviation of inflation.
DEFAULT_INFLATION_VOLATILITY = 0.02

#: How strongly this year's return echoes last year's. Positive and modest:
#: enough to cluster drawdowns, not so much that the model invents momentum.
RETURN_AUTOCORRELATION = 0.15

#: Probability in any given year of an income shock — redundancy, illness, a
#: contract ending. The default is deliberately non-zero: a simulation where
#: nothing ever goes wrong with earning is not a risk model.
DEFAULT_INCOME_SHOCK_ANNUAL_PROBABILITY = 0.04

#: How long an income shock lasts, in months, and how much income it removes.
INCOME_SHOCK_MONTHS = 6
INCOME_SHOCK_SEVERITY = 0.6


class SimulationError(ValueError):
    """A simulation request that cannot be run as asked."""


@dataclass(frozen=True)
class SimulationSettings:
    trials: int = DEFAULT_TRIALS
    seed: int = 12345
    return_volatility: float = DEFAULT_RETURN_VOLATILITY
    inflation_volatility: float = DEFAULT_INFLATION_VOLATILITY
    income_shock_probability: float = DEFAULT_INCOME_SHOCK_ANNUAL_PROBABILITY

    def __post_init__(self) -> None:
        if not 1 <= self.trials <= MAX_TRIALS:
            raise SimulationError(f"trials must be between 1 and {MAX_TRIALS}")
        if self.return_volatility < 0 or self.inflation_volatility < 0:
            raise SimulationError("volatility cannot be negative")
        if not 0 <= self.income_shock_probability <= 1:
            raise SimulationError("income shock probability must be a fraction")

    def describe(self) -> list[str]:
        return [
            f"{self.trials:,} runs, seeded at {self.seed} so this is reproducible.",
            f"Investment returns vary with a {self.return_volatility:.0%} annual standard deviation.",
            f"Inflation varies with a {self.inflation_volatility:.1%} annual standard deviation.",
            (
                f"Each year carries a {self.income_shock_probability:.0%} chance of losing "
                f"{INCOME_SHOCK_SEVERITY:.0%} of income for {INCOME_SHOCK_MONTHS} months."
            ),
            "Bad years cluster rather than arriving independently, which is what makes "
            "a run of them possible at all.",
        ]


@dataclass(frozen=True)
class Percentiles:
    """A distribution reported the way a person can use it."""

    p10: int
    p25: int
    p50: int
    p75: int
    p90: int

    @property
    def spread(self) -> int:
        return self.p90 - self.p10


@dataclass(frozen=True)
class SimulationResult:
    currency: str
    trials: int
    seed: int
    months: int
    #: Closing net worth across trials.
    closing_net_worth: Percentiles
    #: The lowest the liquid balance got, across trials. The number that says
    #: whether a plan survives its worst month, not just its last one.
    trough: Percentiles
    #: Fraction of trials in which liquid balance never went negative.
    success_probability: float
    #: Fraction of trials that ran out of money at some point.
    failure_probability: float
    #: The median month at which failing trials first went negative. None when
    #: nothing failed.
    median_failure_month: int | None
    #: Net worth percentile bands over time, for a fan chart. Sampled rather
    #: than every month — 480 points x 5 bands is more than a chart needs.
    bands: list[dict] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    #: The deterministic single-line projection, for comparison against the
    #: band. Included because "where the smooth assumption put you" is exactly
    #: the thing the spread is arguing with.
    deterministic: ProjectionResult | None = None


def _percentiles(values: list[int]) -> Percentiles:
    if not values:
        return Percentiles(0, 0, 0, 0, 0)
    ordered = sorted(values)

    def at(fraction: float) -> int:
        # Nearest-rank. With a thousand samples the interpolation refinement is
        # far below the precision the inputs justify.
        index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
        return ordered[index]

    return Percentiles(p10=at(0.10), p25=at(0.25), p50=at(0.50), p75=at(0.75), p90=at(0.90))


def _trial_rng(seed: int, trial: int) -> random.Random:
    """The generator for one trial.

    Seeded from `(seed, trial)` rather than drawn from a single stream shared
    across the run. That makes trial *k* depend only on the seed and its own
    index, so asking for more trials refines the estimate instead of moving
    every percentile — which is what lets someone raise the trial count to
    check a result rather than to get a different one.

    A tuple seed rather than `hash()`: string and tuple hashing is randomised
    per process unless PYTHONHASHSEED is pinned, which would have made every
    "reproducible" claim here false across restarts.
    """
    return random.Random(f"{seed}:{trial}")


def _next_shock(rng: random.Random, previous: float) -> float:
    """One year's return shock, in standard deviations, correlated with the
    year before it. Positive autocorrelation is what makes a *run* of bad years
    possible; independent draws quietly cancel and understate the tail."""
    return RETURN_AUTOCORRELATION * previous + (1 - RETURN_AUTOCORRELATION) * rng.gauss(0, 1)


def simulate(
    *,
    position: FinancialPosition,
    assumptions: EconomicAssumptions | None = None,
    events: list[CompiledEvent] | None = None,
    months: int = 120,
    settings: SimulationSettings | None = None,
) -> SimulationResult:
    """Run the projection `trials` times under sampled conditions.

    Each trial re-runs the *real* engine rather than an approximation of it, so
    a scenario's events, debts and life changes are all present in every draw.
    That is slower than modelling the distribution analytically and it is the
    only way the answer stays consistent with the deterministic projection the
    user is looking at beside it.
    """
    if months <= 0 or months > MAX_HORIZON_MONTHS:
        raise SimulationError(f"months must be between 1 and {MAX_HORIZON_MONTHS}")

    base = assumptions or EconomicAssumptions()
    settings = settings or SimulationSettings()
    events = list(events or [])

    closings: list[int] = []
    troughs: list[int] = []
    failures: list[int] = []
    # Net worth at each month across trials, for the fan.
    by_month: list[list[int]] = [[] for _ in range(months)]

    for trial in range(settings.trials):
        rng = _trial_rng(settings.seed, trial)
        result = _run_trial(
            position=position,
            base=base,
            events=events,
            months=months,
            settings=settings,
            rng=rng,
        )
        closings.append(result.closing_net_worth_minor)
        troughs.append(result.lowest_liquid_minor)
        if result.first_negative_month is not None:
            failures.append(result.first_negative_month)
        for index, point in enumerate(result.points):
            by_month[index].append(point.net_worth_minor)

    # Sample the fan rather than emitting every month.
    step = max(1, months // 60)
    bands = []
    for index in range(0, months, step):
        p = _percentiles(by_month[index])
        bands.append(
            {
                "month": index + 1,
                "p10": p.p10,
                "p25": p.p25,
                "p50": p.p50,
                "p75": p.p75,
                "p90": p.p90,
            }
        )

    success = 1 - len(failures) / settings.trials
    deterministic = project(position=position, assumptions=base, events=events, months=months)

    return SimulationResult(
        currency=position.currency,
        trials=settings.trials,
        seed=settings.seed,
        months=months,
        closing_net_worth=_percentiles(closings),
        trough=_percentiles(troughs),
        success_probability=round(success, 4),
        failure_probability=round(1 - success, 4),
        median_failure_month=int(statistics.median(failures)) if failures else None,
        bands=bands,
        assumptions=settings.describe(),
        deterministic=deterministic,
    )


def _run_trial(
    *,
    position: FinancialPosition,
    base: EconomicAssumptions,
    events: list[CompiledEvent],
    months: int,
    settings: SimulationSettings,
    rng: random.Random,
) -> ProjectionResult:
    """One draw: sample a path of conditions, then project along it.

    Conditions are resampled annually rather than monthly. Monthly resampling
    would produce a smoother aggregate through pure averaging — the central
    limit theorem quietly cancelling the very variance the simulation exists to
    show — and annual is also the frequency the assumptions are quoted at.
    """
    years = months // 12 + 1
    shock = 0.0
    segments: list[tuple[int, EconomicAssumptions]] = []
    income_shock_months: set[int] = set()

    for year in range(years):
        shock = _next_shock(rng, shock)
        segments.append(
            (
                year,
                replace(
                    base,
                    annual_investment_return=base.annual_investment_return
                    + shock * settings.return_volatility,
                    annual_inflation=max(
                        -0.02,
                        base.annual_inflation + rng.gauss(0, 1) * settings.inflation_volatility,
                    ),
                ),
            )
        )
        if rng.random() < settings.income_shock_probability:
            start = year * 12 + rng.randrange(12) + 1
            income_shock_months.update(range(start, start + INCOME_SHOCK_MONTHS))

    # The engine takes one assumption set for the whole window, so a sampled
    # *path* is collapsed to its geometric mean return and arithmetic mean
    # inflation. This is the one approximation in the module and it is stated
    # rather than hidden: it preserves the spread across trials, which is what
    # the percentiles measure, while losing within-trial ordering. Sequence
    # risk therefore shows up between trials, not inside one.
    growth = 1.0
    for _, sampled in segments:
        growth *= 1 + sampled.annual_investment_return
    mean_return = growth ** (1 / len(segments)) - 1 if segments else base.annual_investment_return
    mean_inflation = statistics.fmean(s.annual_inflation for _, s in segments)

    trial_assumptions = replace(
        base,
        annual_investment_return=max(-0.5, min(2.0, mean_return)),
        annual_inflation=max(-0.5, min(2.0, mean_inflation)),
    )

    trial_events = list(events)
    in_window = sorted(m for m in income_shock_months if m <= months)
    if in_window:
        # Only the first shock in a trial is modelled. Stacking several would
        # compound into a scenario ("laid off three times in a decade") that is
        # real but rare enough that including it would let a handful of trials
        # dominate the lower percentiles.
        start = in_window[0]
        trial_events.append(
            CompiledEvent(
                label="Income shock",
                start_month=start,
                end_month=min(months, start + INCOME_SHOCK_MONTHS - 1),
                monthly_income_delta_minor=-round(position.monthly_net_income_minor * INCOME_SHOCK_SEVERITY),
            )
        )

    return project(position=position, assumptions=trial_assumptions, events=trial_events, months=months)
