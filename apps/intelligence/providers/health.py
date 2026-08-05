"""Financial health scoring — a transparent weighted composite.

Five components, each scored 0..100, combined by fixed weights into an overall
0..100 with a plain-language band. Transparency is the whole point: a health
score people can't decompose is a horoscope. Every component ships with a
one-line detail, and the weights are explicit and tunable via config.

An LLM tier would turn `HealthScore.components` into personalized narrative
advice — but the number itself stays deterministic and auditable, so two users
with the same inputs always get the same score.
"""

from __future__ import annotations

from ..protocols import (
    HealthComponent,
    HealthInputs,
    HealthScore,
    HealthScoreProvider,
    Provenance,
    ProviderKind,
)

VERSION = "1.0.0"

# component -> weight; must sum to 1.0 (asserted in tests)
WEIGHTS = {
    "savings_rate": 0.25,
    "emergency_fund": 0.25,
    "budget_adherence": 0.20,
    "debt_load": 0.20,
    "income_stability": 0.10,
}


#: Least share of the total weight that has to be measurable before an overall
#: number is stated at all. Below this the score would be a claim about a
#: household from one or two facts about it, which is worse than no score.
MIN_COVERAGE = 0.5

#: Band used when there is not enough measurable data to state a score.
INSUFFICIENT_BAND = "not enough data"


def _clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def _band(score: int) -> str:
    if score >= 80:
        return "excellent"
    if score >= 60:
        return "good"
    if score >= 40:
        return "fair"
    return "needs attention"


class WeightedHealthScorer(HealthScoreProvider):
    """Weighted composite over whatever is actually measurable.

    Unmeasurable components are dropped from the mean and their weight is
    redistributed across the rest, rather than being scored as zero (which
    would punish a household for data it hasn't entered) or as full marks
    (which is the bug this replaced). What was left out is reported alongside,
    so a partial score is never mistaken for a complete one.
    """

    def score(self, inputs: HealthInputs) -> HealthScore:
        components = (
            self._savings(inputs.savings_rate),
            self._emergency(inputs.essential_coverage_months),
            self._adherence(inputs.budget_adherence),
            self._debt(inputs.debt_to_asset),
            self._stability(inputs.income_stability),
        )

        measured = [c for c in components if c.score is not None]
        available_weight = sum(c.weight for c in measured)
        coverage = round(available_weight, 3)

        if available_weight < MIN_COVERAGE:
            return HealthScore(
                score=None,
                band=INSUFFICIENT_BAND,
                components=components,
                coverage=coverage,
                provenance=Provenance(
                    provider="WeightedHealthScorer",
                    kind=ProviderKind.RULE,
                    version=VERSION,
                    rationale=(
                        f"Only {coverage:.0%} of the score is measurable so far; "
                        f"at least {MIN_COVERAGE:.0%} is needed to state a figure."
                    ),
                ),
            )

        # Renormalise over what was measured, so the components that *do* have
        # a basis carry the full 0..100 range between them.
        overall = _clamp_score(sum(c.score * c.weight for c in measured) / available_weight)

        return HealthScore(
            score=overall,
            band=_band(overall),
            components=components,
            coverage=coverage,
            provenance=Provenance(
                provider="WeightedHealthScorer",
                kind=ProviderKind.RULE,
                version=VERSION,
                rationale=(
                    "Weighted mean of the measurable components; weights in WEIGHTS, "
                    f"renormalised over {coverage:.0%} of the total weight."
                ),
            ),
        )

    # -- components ---------------------------------------------------------
    # Each returns a scored component, or an unscored one explaining what is
    # missing. None in, None out — no component invents its own input.

    @staticmethod
    def _savings(rate: float | None) -> HealthComponent:
        weight = WEIGHTS["savings_rate"]
        if rate is None:
            return HealthComponent(
                "Savings rate",
                None,
                weight,
                "Not enough income and spending recorded yet to measure what you keep.",
            )
        # 20% of income kept -> full marks.
        return HealthComponent(
            "Savings rate", _clamp_score(min(rate / 0.20, 1.0) * 100), weight, f"Keeping {rate * 100:.0f}% of income."
        )

    @staticmethod
    def _emergency(months: float | None) -> HealthComponent:
        weight = WEIGHTS["emergency_fund"]
        if months is None:
            return HealthComponent(
                "Emergency fund",
                None,
                weight,
                "No regular spending recorded yet, so there is nothing to measure a runway against.",
            )
        # 6 months' runway -> full marks.
        return HealthComponent(
            "Emergency fund",
            _clamp_score(min(months / 6.0, 1.0) * 100),
            weight,
            f"{months:.1f} months of essentials covered by cash you can reach.",
        )

    @staticmethod
    def _adherence(adherence: float | None) -> HealthComponent:
        weight = WEIGHTS["budget_adherence"]
        if adherence is None:
            return HealthComponent(
                "Budget adherence", None, weight, "No budgets set, so there is nothing to keep to."
            )
        return HealthComponent(
            "Budget adherence",
            _clamp_score(adherence * 100),
            weight,
            f"{adherence * 100:.0f}% of budgets within limit.",
        )

    @staticmethod
    def _debt(ratio: float | None) -> HealthComponent:
        weight = WEIGHTS["debt_load"]
        if ratio is None:
            return HealthComponent(
                "Debt load", None, weight, "No accounts recorded yet, so there is no balance sheet to read."
            )
        # debt/asset 0 -> 100, 1.0+ -> 0 (linear, floored)
        return HealthComponent(
            "Debt load",
            _clamp_score((1.0 - min(ratio, 1.0)) * 100),
            weight,
            f"Debt is {ratio * 100:.0f}% of assets.",
        )

    @staticmethod
    def _stability(stability: float | None) -> HealthComponent:
        weight = WEIGHTS["income_stability"]
        if stability is None:
            return HealthComponent(
                "Income stability",
                None,
                weight,
                "Needs a couple of months of income history before it means anything.",
            )
        return HealthComponent(
            "Income stability",
            _clamp_score(stability * 100),
            weight,
            f"Income stability {stability * 100:.0f}%.",
        )
