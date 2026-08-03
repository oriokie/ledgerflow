"""Debt Stress Score — how much pressure this debt is putting on someone.

Pure arithmetic, no ORM, for the same reasons as `payoff.py`: it must be
directly testable and identically reproducible.

The score is 0–100 where **higher is better**, matching the financial health
score already in the product. Inverting one relative to the other would be a
persistent source of misreading.

Two commitments shape the design:

**Every component is explained, not just scored.** `explain()` returns the
inputs, each component's contribution, and a sentence saying why. A score
someone can't interrogate is a number they'll either over-trust or ignore, and
both are worse than no score.

**Missing inputs are excluded, never defaulted.** Someone who hasn't recorded
their income shouldn't be scored as if they earn nothing — that would produce
an alarming figure derived from an absence. Components without data are dropped
and the remaining weights renormalised, with `coverage` reporting how much of
the score was actually measurable.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

#: Component weights. They sum to 1.0 when everything is measurable; when a
#: component is dropped for want of data the rest are renormalised.
WEIGHTS = {
    "debt_to_income": 0.25,
    "minimum_payment_ratio": 0.20,
    "interest_burden": 0.20,
    "utilisation": 0.15,
    "average_apr": 0.10,
    "payoff_duration": 0.10,
}

#: Below this share of the score being measurable, a headline number would be
#: more misleading than useful.
MIN_COVERAGE = 0.5


@dataclass(frozen=True, slots=True)
class StressInputs:
    """Everything the score can use. Every field is optional by design."""

    total_balance_minor: int = 0
    total_minimum_minor: int = 0
    monthly_interest_minor: int = 0
    #: Net monthly income. `None` when unknown — see the module docstring.
    monthly_income_minor: int | None = None
    #: Total revolving credit available, for utilisation. Cards only: a
    #: mortgage has no limit to be a percentage of.
    total_credit_limit_minor: int | None = None
    revolving_balance_minor: int = 0
    weighted_apr: float = 0.0
    months_to_debt_free: int | None = None
    #: Payments missed in the last 12 months, when the data exists.
    missed_payments_12m: int | None = None


@dataclass(frozen=True, slots=True)
class Component:
    key: str
    label: str
    #: 0–100, higher is better.
    score: int
    weight: float
    #: The measured figure, for display.
    value: float | None
    detail: str


@dataclass(frozen=True, slots=True)
class StressScore:
    score: int
    band: str
    components: tuple[Component, ...]
    #: Share of the weighting that had data behind it, 0–1.
    coverage: float
    #: True when too little was measurable for the headline to mean much.
    is_provisional: bool
    #: Applied after weighting; see `_missed_payment_penalty`.
    missed_payment_penalty: int = 0


def _band(score: int) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "moderate"
    if score >= 30:
        return "high"
    return "critical"


def _scale(value: float, *, best: float, worst: float) -> int:
    """Map a measurement onto 0–100, clamped.

    `best` and `worst` are the ends of the range that actually discriminates.
    Beyond them the score saturates: someone at eight times their income in
    debt is not meaningfully better off than someone at ten, and pretending the
    scale continues would understate both.
    """
    if worst == best:
        return 100
    fraction = (value - best) / (worst - best)
    return int(round(max(0.0, min(1.0, 1.0 - fraction)) * 100))


def _missed_payment_penalty(missed: int | None) -> int:
    """A flat deduction for missed payments.

    Deliberately a penalty rather than a weighted component. Missed payments
    are categorically different from a ratio being unflattering — they carry
    fees, mark a credit file, and often signal the situation has already
    slipped. Averaging that away against a good utilisation figure would let a
    real problem hide behind an unrelated strength.
    """
    if not missed:
        return 0
    return min(25, missed * 8)


def compute(inputs: StressInputs) -> StressScore:
    """Score the pressure this debt represents, and explain how."""
    components: list[Component] = []

    # --- debt to income -----------------------------------------------------
    if inputs.monthly_income_minor and inputs.monthly_income_minor > 0:
        annual_income = inputs.monthly_income_minor * 12
        ratio = inputs.total_balance_minor / annual_income
        components.append(
            Component(
                key="debt_to_income",
                label="Debt to income",
                # Under 0.5× annual income is comfortable; 4× and beyond is
                # where the ratio stops discriminating.
                score=_scale(ratio, best=0.5, worst=4.0),
                weight=WEIGHTS["debt_to_income"],
                value=round(ratio, 2),
                detail=(
                    f"You owe about {ratio:.1f}× your annual income."
                    if ratio >= 0.1
                    else "Your debt is small relative to what you earn."
                ),
            )
        )

    # --- minimum payments against income ------------------------------------
    if inputs.monthly_income_minor and inputs.monthly_income_minor > 0:
        ratio = inputs.total_minimum_minor / inputs.monthly_income_minor
        components.append(
            Component(
                key="minimum_payment_ratio",
                label="Payments vs income",
                # 10% of income on debt service is manageable; 40% is severe.
                score=_scale(ratio, best=0.10, worst=0.40),
                weight=WEIGHTS["minimum_payment_ratio"],
                value=round(ratio * 100, 1),
                detail=(
                    f"Minimum payments take about {ratio * 100:.0f}% of your monthly income."
                ),
            )
        )

    # --- how much of the payment is just interest ---------------------------
    if inputs.total_minimum_minor > 0:
        ratio = inputs.monthly_interest_minor / inputs.total_minimum_minor
        components.append(
            Component(
                key="interest_burden",
                label="Interest burden",
                # At 70%+ of the payment going to interest the balance barely
                # moves, which is the situation this component exists to catch.
                score=_scale(ratio, best=0.15, worst=0.70),
                weight=WEIGHTS["interest_burden"],
                value=round(ratio * 100, 1),
                detail=(
                    f"About {ratio * 100:.0f}% of your minimum payments goes to interest "
                    "rather than reducing the balance."
                ),
            )
        )

    # --- revolving utilisation ----------------------------------------------
    if inputs.total_credit_limit_minor and inputs.total_credit_limit_minor > 0:
        ratio = inputs.revolving_balance_minor / inputs.total_credit_limit_minor
        components.append(
            Component(
                key="utilisation",
                label="Credit utilisation",
                score=_scale(ratio, best=0.10, worst=0.80),
                weight=WEIGHTS["utilisation"],
                value=round(ratio * 100, 1),
                detail=f"You're using about {ratio * 100:.0f}% of your available credit.",
            )
        )

    # --- average rate --------------------------------------------------------
    if inputs.weighted_apr > 0:
        components.append(
            Component(
                key="average_apr",
                label="Average rate",
                score=_scale(inputs.weighted_apr, best=5.0, worst=25.0),
                weight=WEIGHTS["average_apr"],
                value=round(inputs.weighted_apr, 2),
                detail=f"Your balance-weighted rate is about {inputs.weighted_apr:.1f}%.",
            )
        )

    # --- how long until it's gone -------------------------------------------
    if inputs.months_to_debt_free is not None:
        months = inputs.months_to_debt_free
        components.append(
            Component(
                key="payoff_duration",
                label="Time to clear",
                score=_scale(float(months), best=12.0, worst=120.0),
                weight=WEIGHTS["payoff_duration"],
                value=float(months),
                detail=(
                    f"At current payments you'd be debt free in about {months} months."
                ),
            )
        )
    elif inputs.total_balance_minor > 0 and inputs.total_minimum_minor > 0:
        # No completion date means the plan never finishes — the worst possible
        # answer for this component, and a real one.
        components.append(
            Component(
                key="payoff_duration",
                label="Time to clear",
                score=0,
                weight=WEIGHTS["payoff_duration"],
                value=None,
                detail="At current payments this debt never clears.",
            )
        )

    if not components:
        return StressScore(
            score=100,
            band="excellent",
            components=(),
            coverage=0.0,
            is_provisional=True,
        )

    measured_weight = sum(c.weight for c in components)
    coverage = round(measured_weight / sum(WEIGHTS.values()), 2)

    # Renormalise across whatever could be measured, so a missing component
    # neither drags the score down nor silently props it up.
    weighted = sum(c.score * c.weight for c in components) / measured_weight
    penalty = _missed_payment_penalty(inputs.missed_payments_12m)
    final = int(round(max(0.0, min(100.0, weighted - penalty))))

    return StressScore(
        score=final,
        band=_band(final),
        components=tuple(sorted(components, key=lambda c: c.score)),
        coverage=coverage,
        is_provisional=coverage < MIN_COVERAGE,
        missed_payment_penalty=penalty,
    )


def explain(score: StressScore) -> dict:
    """The full derivation, for a UI that has to justify the number.

    Components come back weakest-first, because the lowest-scoring one is where
    an improvement moves the total most — which is the only actionable thing a
    composite score has to say.
    """
    return {
        "score": score.score,
        "band": score.band,
        "coverage": score.coverage,
        "is_provisional": score.is_provisional,
        "missed_payment_penalty": score.missed_payment_penalty,
        "weakest": score.components[0].key if score.components else None,
        "components": [
            {
                "key": c.key,
                "label": c.label,
                "score": c.score,
                "weight": round(c.weight, 3),
                "value": c.value,
                "detail": c.detail,
            }
            for c in score.components
        ],
        "method": (
            "Each component is scored 0–100 where higher is better, then combined "
            "by weight. Components with no data are excluded and the remaining "
            "weights renormalised, so a missing figure never counts as a bad one."
        ),
    }
