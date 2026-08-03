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
    def score(self, inputs: HealthInputs) -> HealthScore:
        # Each sub-score maps a raw metric onto 0..100 with a defensible curve.
        savings = _clamp_score(inputs.savings_rate * 100 / 0.20 * 100 / 100)  # 20% savings -> 100
        savings = _clamp_score(min(inputs.savings_rate / 0.20, 1.0) * 100)

        # 6 months' runway -> 100
        emergency = _clamp_score(min(inputs.essential_coverage_months / 6.0, 1.0) * 100)

        adherence = _clamp_score(inputs.budget_adherence * 100)

        # debt/asset 0 -> 100, 1.0+ -> 0 (linear, floored)
        debt = _clamp_score((1.0 - min(inputs.debt_to_asset, 1.0)) * 100)

        stability = _clamp_score(inputs.income_stability * 100)

        components = (
            HealthComponent(
                "Savings rate",
                savings,
                WEIGHTS["savings_rate"],
                f"Keeping {inputs.savings_rate * 100:.0f}% of income.",
            ),
            HealthComponent(
                "Emergency fund",
                emergency,
                WEIGHTS["emergency_fund"],
                f"{inputs.essential_coverage_months:.1f} months of essentials covered.",
            ),
            HealthComponent(
                "Budget adherence",
                adherence,
                WEIGHTS["budget_adherence"],
                f"{inputs.budget_adherence * 100:.0f}% of budgets within limit.",
            ),
            HealthComponent(
                "Debt load",
                debt,
                WEIGHTS["debt_load"],
                f"Debt is {inputs.debt_to_asset * 100:.0f}% of assets.",
            ),
            HealthComponent(
                "Income stability",
                stability,
                WEIGHTS["income_stability"],
                f"Income stability {inputs.income_stability * 100:.0f}%.",
            ),
        )

        overall = _clamp_score(sum(c.score * c.weight for c in components))

        return HealthScore(
            score=overall,
            band=_band(overall),
            components=components,
            provenance=Provenance(
                provider="WeightedHealthScorer",
                kind=ProviderKind.RULE,
                version=VERSION,
                rationale="Weighted mean of five components; weights in WEIGHTS.",
            ),
        )
