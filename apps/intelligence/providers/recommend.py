"""Heuristic recommender — actionable, engine-grounded suggestions.

Reasons over a pre-computed `RecommendationContext` (built by a selector from
real engine reads) and emits `Recommendation`s whose `action` payloads map to
capabilities the engine ACTUALLY has — so "Move $62" is a real budget-line
edit. A recommendation the product can't execute is worse than none, so this
provider only emits actions it can back — which is why an upcoming bill
points at the Bills page rather than a fabricated "schedule a transfer"
action: a Bill is settled against a Payee, not moved between two of the
user's own accounts, and there is no model support for scheduling one.

Severity mirrors the dashboard's insight tiers (attention/soon/good), and —
consistent with that design — positive recommendations carry no action.
"""

from __future__ import annotations

from ..protocols import (
    Provenance,
    ProviderKind,
    Recommendation,
    RecommendationContext,
    RecommendationKind,
    RecommendationProvider,
)

VERSION = "1.0.0"


class HeuristicRecommender(RecommendationProvider):
    def recommend(self, context: RecommendationContext) -> list[Recommendation]:
        out: list[Recommendation] = []
        prov = Provenance(provider="HeuristicRecommender", kind=ProviderKind.RULE, version=VERSION)

        # 1. Budget rebalance: an over-budget line + an underspent line that can
        #    cover the overage without changing the month's total.
        for over in context.over_budget_lines:
            overage = over.get("overage_minor", 0)
            donor = next(
                (u for u in context.underspent_lines if u.get("remaining_minor", 0) >= overage),
                None,
            )
            if donor and overage > 0:
                out.append(
                    Recommendation(
                        kind=RecommendationKind.BUDGET_REBALANCE,
                        title=f"{over['name']} is over by {overage / 100:.2f}",
                        body=(
                            f"{donor['name']} has {donor['remaining_minor'] / 100:.2f} unspent. "
                            f"Moving {overage / 100:.2f} covers the gap without changing your month's total."
                        ),
                        severity="attention",
                        action={
                            "action": "budget_rebalance",
                            "from_line_id": donor["line_id"],
                            "to_line_id": over["line_id"],
                            "amount_minor": overage,
                        },
                        provenance=prov,
                    )
                )

        # 2. Upcoming bill: point at the Bills page, where marking it paid is a
        #    real, existing action. Nothing here is fabricated — every field
        #    the DTO carries is one this recommendation actually uses.
        for bill in context.upcoming_bills:
            out.append(
                Recommendation(
                    kind=RecommendationKind.BILL_UPCOMING,
                    title=f"{bill['name']} due {bill['due_label']}",
                    body=(
                        f"{bill['amount_minor'] / 100:.2f} due {bill['due_label']}. "
                        "Mark it paid once it's settled, or review it on the Bills page."
                    ),
                    severity="soon",
                    action={"action": "bill_upcoming", "bill_id": bill["bill_id"]},
                    provenance=prov,
                )
            )

        # 3. Savings opportunity: positive reinforcement, NO action (good news
        #    doesn't nag — mirrors the dashboard insight rule).
        if context.savings_rate >= 0.15:
            out.append(
                Recommendation(
                    kind=RecommendationKind.SAVINGS_OPPORTUNITY,
                    title=f"You're saving {context.savings_rate * 100:.0f}% of income",
                    body="On track and ahead of the 15% guideline. Nothing to do — keep it up.",
                    severity="good",
                    action={},
                    provenance=prov,
                )
            )

        return out
