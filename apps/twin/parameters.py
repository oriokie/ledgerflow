"""The digital twin — the household's own numbers, replacing our guesses.

Phase 1 shipped an engine that projects forward from a set of economic
assumptions, and those assumptions were *defaults*: 5% inflation, 3% salary
growth, a smooth 7% return. Sensible, arguable, and identical for every
household in the product. This module is the part that makes them the
household's own.

**What "learns" honestly means here.** Not a model that trains. A set of
parameters measured from the ledger, each of which gets narrower as more months
land — and each of which reports how much evidence it rests on, so a projection
built on two months says so rather than presenting itself with the same
confidence as one built on three years.

The five things worth measuring, because they are the ones the engine's
defaults get most wrong for any particular household:

*Income volatility* — the default engine treats income as a smooth line. For a
salaried employee that is nearly true; for a contractor it is a fiction that
hides every month they earned nothing. Measured as the coefficient of variation
of monthly inflows.

*Spending growth* — the household's own inflation, which is routinely nothing
like the published figure, because it is a weighted average of *their* basket.

*Saving consistency* — how reliably the surplus actually gets saved. A
household that saves 30% in good months and nothing in others has a very
different trajectory from one that saves 15% every month, and the mean is the
same.

*Budget adherence* — whether the plan predicts the behaviour. When it does not,
every projection built on planned figures rather than observed ones is wrong in
a knowable direction.

*Debt behaviour* — whether payments actually exceed the minimum, which decides
whether a payoff date is a plan or a hope.

**Evidence, always.** Every parameter carries `months_observed` and a
`confidence`, and `to_assumptions()` refuses to override a default until there
is enough behind it. A measured figure from two months is not better than a
sensible prior — it is noisier, and swapping one in because it is "real data"
is how a product ends up projecting a household's whole future from a January
with a bonus in it.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from apps.projections.engine import EconomicAssumptions

#: Below this many complete months, a measurement is noise wearing a number and
#: the prior stands. Six is where a median stops moving much on this data.
MIN_MONTHS_FOR_CONFIDENCE = 6

#: Where a measurement is trusted outright rather than blended with the prior.
STRONG_EVIDENCE_MONTHS = 18

#: Trailing window. Long enough to see a year's seasonality, short enough that
#: a job change three years ago does not still dominate.
WINDOW_MONTHS = 24


class Confidence:
    NONE = "none"  # nothing measured
    WEAK = "weak"  # measured, but the prior still leads
    MODERATE = "moderate"  # blended
    STRONG = "strong"  # the household's own figure stands alone


def _confidence_for(months: int) -> str:
    if months < 2:
        return Confidence.NONE
    if months < MIN_MONTHS_FOR_CONFIDENCE:
        return Confidence.WEAK
    if months < STRONG_EVIDENCE_MONTHS:
        return Confidence.MODERATE
    return Confidence.STRONG


def _blend_weight(months: int) -> float:
    """How much of the measured value to trust, 0..1.

    Ramps linearly from the confidence floor to strong evidence rather than
    switching at a threshold. A parameter that jumps the moment a sixth month
    lands makes the whole projection lurch, and a user watching it move has no
    way to tell a real change in their life from an artefact of our cutoff.
    """
    if months < MIN_MONTHS_FOR_CONFIDENCE:
        return 0.0
    if months >= STRONG_EVIDENCE_MONTHS:
        return 1.0
    span = STRONG_EVIDENCE_MONTHS - MIN_MONTHS_FOR_CONFIDENCE
    return (months - MIN_MONTHS_FOR_CONFIDENCE) / span


@dataclass(frozen=True)
class Parameter:
    """One measured behaviour, with the evidence behind it."""

    key: str
    label: str
    #: The household's measured value. None when there is nothing to measure.
    measured: float | None
    #: What the engine would assume without them.
    prior: float
    months_observed: int
    confidence: str
    detail: str

    @property
    def effective(self) -> float:
        """The value a projection should actually use.

        A blend, weighted by evidence. Below the floor this is exactly the
        prior, which is the point: we do not pretend two months of data beats a
        considered default.
        """
        if self.measured is None:
            return self.prior
        w = _blend_weight(self.months_observed)
        return self.prior * (1 - w) + self.measured * w

    @property
    def differs_from_prior(self) -> bool:
        if self.measured is None:
            return False
        base = abs(self.prior) or 1.0
        return abs(self.measured - self.prior) / base > 0.15


@dataclass(frozen=True)
class DigitalTwin:
    currency: str
    as_of: date
    months_observed: int
    parameters: list[Parameter] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def get(self, key: str) -> Parameter | None:
        return next((p for p in self.parameters if p.key == key), None)

    @property
    def confidence(self) -> str:
        """The twin is only as trustworthy as its thinnest parameter."""
        if not self.parameters:
            return Confidence.NONE
        order = [Confidence.NONE, Confidence.WEAK, Confidence.MODERATE, Confidence.STRONG]
        return min((p.confidence for p in self.parameters), key=order.index)

    def to_assumptions(self, base: EconomicAssumptions | None = None) -> EconomicAssumptions:
        """The engine's assumptions, with what we have measured folded in.

        Only spending growth is substituted today, because it is the one the
        household's own ledger genuinely measures. Income volatility and saving
        consistency describe *shape* rather than a rate, and the engine takes a
        single smooth figure — so they inform the simulation's volatility and
        the twin's narrative instead of silently bending a mean. Claiming to
        have personalised a parameter we cannot actually derive would be worse
        than leaving the prior in place.
        """
        base = base or EconomicAssumptions()
        spending = self.get("spending_growth")
        if spending is None:
            return base
        from dataclasses import replace

        return replace(base, annual_inflation=round(spending.effective, 4))


def _monthly_flows(as_of: date) -> list[tuple[date, int, int]]:
    """(month, inflow, outflow) for complete months only, oldest first.

    The current month is excluded for the same reason it is everywhere else in
    this product: it is not finished, so it always looks frugal, and including
    it teaches the twin that the household spends less than it does.

    **Months with no activity at all are excluded too**, and that one is less
    obvious. `cashflow_statement` emits a row for every month in the window
    whether or not anything happened in it, so a workspace with three months of
    transactions inside a twenty-four-month window returns twenty-three rows.
    Counting those as evidence would tell the twin it had two years of history
    behind a measurement made from one quarter — the precise mistake the
    evidence weighting exists to prevent, arriving through the back door.
    """
    from apps.finance import selectors as finance_selectors

    statement = finance_selectors.cashflow_statement(months=WINDOW_MONTHS, as_of=as_of)
    if statement is None:
        return []
    current_month = as_of.replace(day=1)
    return [
        (row.period_start, row.inflow_minor, row.outflow_minor)
        for row in statement.rows
        if row.period_start < current_month and (row.inflow_minor or row.outflow_minor)
    ]


def _income_volatility(flows) -> tuple[float | None, str]:
    inflows = [inflow for _m, inflow, _o in flows if inflow > 0]
    if len(inflows) < 2:
        return None, "Not enough months with recorded income to measure steadiness."
    mean = statistics.fmean(inflows)
    if mean <= 0:
        return None, "No income recorded."
    cv = statistics.pstdev(inflows) / mean
    if cv < 0.10:
        shape = "very steady — a salary, near enough"
    elif cv < 0.25:
        shape = "mostly steady, with some variation"
    else:
        shape = "irregular, which is what makes a cash buffer matter more than the average"
    return round(cv, 4), f"Month-to-month income varies by about {cv:.0%}: {shape}."


def _spending_growth(flows) -> tuple[float | None, str]:
    """The household's own inflation, annualised.

    Compares the first and last thirds of the window rather than fitting a line
    across it: a regression is dominated by whichever end has the outlier, and
    on this many points the two-block comparison is both more robust and easier
    to explain to the person it is about.
    """
    outflows = [out for _m, _i, out in flows if out > 0]
    if len(outflows) < 6:
        return None, "Fewer than six complete months of spending — too few to see a trend."
    third = max(1, len(outflows) // 3)
    early = statistics.fmean(outflows[:third])
    late = statistics.fmean(outflows[-third:])
    if early <= 0:
        return None, "No early spending to compare against."
    months_between = len(outflows) - third
    if months_between <= 0:
        return None, "Window too short to compare."
    growth = (late / early) ** (12 / months_between) - 1
    growth = max(-0.5, min(2.0, growth))
    return round(growth, 4), (
        f"Your own spending has moved about {growth:.1%} a year — this is your basket, "
        "not the published inflation figure."
    )


def _saving_consistency(flows) -> tuple[float | None, str]:
    """The share of months that ended with anything left over.

    A rate, not an amount, and deliberately: a household saving 30% in good
    months and nothing in others has a different trajectory from one saving 15%
    every month, and their averages are identical.
    """
    complete = [(i, o) for _m, i, o in flows if i > 0 or o > 0]
    if len(complete) < 3:
        return None, "Too few complete months to see how consistently you save."
    saved = sum(1 for inflow, out in complete if inflow - out > 0)
    rate = saved / len(complete)
    return round(rate, 4), (f"{saved} of the last {len(complete)} complete months ended with a surplus.")


def _budget_adherence() -> tuple[float | None, str]:
    """Whether the plan predicts the behaviour.

    Read from the budgeting context if it has periods to compare; otherwise
    reported as unmeasured rather than assumed perfect, because assuming a
    household sticks to its budget is exactly the flattering default this
    module exists to remove.
    """
    try:
        from apps.budgeting.models import Budget

        budgets = list(Budget.objects.all()[:50])
    except Exception:  # pragma: no cover - budgeting optional
        return None, "Budgets are not available in this workspace."
    if not budgets:
        return None, "No budgets set, so there is no plan to compare behaviour against."
    return None, (
        f"{len(budgets)} budget(s) recorded. Adherence is reported on the budgets page; "
        "the twin does not re-derive it."
    )


def _debt_behaviour() -> tuple[float | None, str]:
    from apps.debt import selectors as debt_selectors

    views = [v for v in debt_selectors.debt_views() if v.balance_minor > 0]
    if not views:
        return None, "No debts on record."
    covering = sum(1 for v in views if v.minimum_covers_interest)
    return round(covering / len(views), 4), (
        f"{covering} of {len(views)} debts have a payment that clears its interest. "
        "The rest grow even when paid on time."
    )


def build(*, as_of: date | None = None) -> DigitalTwin:
    """Measure the household and return its twin."""
    as_of = as_of or timezone.localdate()

    from apps.finance import selectors as finance_selectors

    currency = finance_selectors._dominant_liquid_currency() or "USD"
    flows = _monthly_flows(as_of)
    months = len(flows)
    prior = EconomicAssumptions()

    volatility, volatility_detail = _income_volatility(flows)
    growth, growth_detail = _spending_growth(flows)
    consistency, consistency_detail = _saving_consistency(flows)
    adherence, adherence_detail = _budget_adherence()
    debt, debt_detail = _debt_behaviour()

    parameters = [
        Parameter(
            key="spending_growth",
            label="Your own inflation",
            measured=growth,
            prior=prior.annual_inflation,
            months_observed=months,
            confidence=_confidence_for(months),
            detail=growth_detail,
        ),
        Parameter(
            key="income_volatility",
            label="How steady your income is",
            measured=volatility,
            prior=0.10,
            months_observed=months,
            confidence=_confidence_for(months),
            detail=volatility_detail,
        ),
        Parameter(
            key="saving_consistency",
            label="How often you finish a month ahead",
            measured=consistency,
            prior=0.5,
            months_observed=months,
            confidence=_confidence_for(months),
            detail=consistency_detail,
        ),
        Parameter(
            key="budget_adherence",
            label="Whether the plan predicts the behaviour",
            measured=adherence,
            prior=1.0,
            months_observed=months,
            confidence=Confidence.NONE if adherence is None else _confidence_for(months),
            detail=adherence_detail,
        ),
        Parameter(
            key="debt_behaviour",
            label="Whether your payments are clearing interest",
            measured=debt,
            prior=1.0,
            months_observed=months,
            confidence=Confidence.NONE if debt is None else _confidence_for(months),
            detail=debt_detail,
        ),
    ]

    notes = [
        "These are measured from your own ledger, not assumed. Each one gets narrower "
        "as more complete months land.",
    ]
    if months < MIN_MONTHS_FOR_CONFIDENCE:
        notes.append(
            f"Only {months} complete month(s) on record. Below {MIN_MONTHS_FOR_CONFIDENCE} "
            "the projection still uses the standard assumptions — a measurement from this "
            "little history is noisier than a sensible default, not better than one."
        )
    if volatility is not None and volatility > 0.25:
        notes.append(
            "Your income is irregular enough that the average is a poor guide. The "
            "simulation's spread matters more here than any single projection line."
        )
    return DigitalTwin(
        currency=currency,
        as_of=as_of,
        months_observed=months,
        parameters=parameters,
        notes=notes,
    )
