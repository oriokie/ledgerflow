"""Insight scoring — deciding what the user sees first.

A coach that surfaces twenty things surfaces nothing. Ranking is the feature,
not a nicety: the difference between useful and ignored is whether the first
item on the list is the one that matters today.

The score is a pure function of the candidate, deliberately:

  * it is directly testable without a database or a provider;
  * the same candidate always scores the same, so the feed is stable between
    runs and a user isn't shown a different order every refresh;
  * an LLM-authored candidate is scored by *our* rules, not by the model's own
    opinion of its importance. A provider that could rank itself first would
    eventually rank itself first for everything.

Four factors, in descending weight:

  severity     — what kind of thing this is (a deadline outranks an idea)
  magnitude    — how much money is at stake, relative to the user's own scale
  urgency      — how soon it matters
  confidence   — how sure the provider is

Magnitude is scaled against the user's own figures rather than absolute
amounts, so £200 means something different to someone spending £800 a month
than to someone spending £8,000. Absolute thresholds are how a coach ends up
shouting at wealthy users and whispering at everyone else.
"""

from __future__ import annotations

from datetime import date

from .models import InsightSeverity

#: Base points by severity. The gap between CRITICAL and WARNING is wide on
#: purpose: a predicted overdraft should outrank every opportunity, however
#: large, because one has a deadline and the other doesn't.
SEVERITY_BASE: dict[str, int] = {
    InsightSeverity.CRITICAL: 60,
    InsightSeverity.WARNING: 40,
    InsightSeverity.OPPORTUNITY: 22,
    InsightSeverity.INFO: 10,
}

#: Maximum points contributed by each remaining factor.
MAX_MAGNITUDE_POINTS = 22
MAX_URGENCY_POINTS = 12
MAX_CONFIDENCE_POINTS = 6

#: An amount at or above this share of the user's monthly baseline earns full
#: magnitude points. A quarter of a month's spending is genuinely significant
#: at any income level.
MAGNITUDE_SATURATION = 0.25

#: Days within which an insight counts as fully urgent.
URGENCY_HORIZON_DAYS = 30


def magnitude_points(amount_minor: int | None, monthly_baseline_minor: int | None) -> int:
    """Points for how much money is at stake, relative to the user's own scale.

    Returns 0 when either figure is missing or the baseline is unusable — an
    insight without a quantified stake shouldn't borrow importance it hasn't
    demonstrated, and dividing by an unknown baseline would invent a ratio.
    """
    if not amount_minor or not monthly_baseline_minor or monthly_baseline_minor <= 0:
        return 0
    ratio = abs(amount_minor) / monthly_baseline_minor
    return round(MAX_MAGNITUDE_POINTS * min(1.0, ratio / MAGNITUDE_SATURATION))


def urgency_points(due_on: date | None, as_of: date) -> int:
    """Points for how soon this matters.

    Something already overdue is maximally urgent; something a month or more
    away earns nothing extra. Undated insights get no urgency points rather
    than a default, because "no deadline" is not "distant deadline".
    """
    if due_on is None:
        return 0
    days = (due_on - as_of).days
    if days <= 0:
        return MAX_URGENCY_POINTS
    if days >= URGENCY_HORIZON_DAYS:
        return 0
    remaining = (URGENCY_HORIZON_DAYS - days) / URGENCY_HORIZON_DAYS
    return round(MAX_URGENCY_POINTS * remaining)


def confidence_points(confidence: float) -> int:
    """Points for provider certainty, clamped to a sane range.

    Weighted lightly on purpose. A confident wrong insight and an unsure right
    one should not be separated mainly by how sure the provider claims to be —
    especially once an LLM is supplying that number about itself.
    """
    clamped = max(0.0, min(1.0, confidence))
    return round(MAX_CONFIDENCE_POINTS * clamped)


def score_insight(
    *,
    severity: str,
    as_of: date,
    amount_minor: int | None = None,
    monthly_baseline_minor: int | None = None,
    due_on: date | None = None,
    confidence: float = 1.0,
) -> int:
    """Final priority, 0-100.

    Clamped rather than normalised: the ceiling is reached only by a critical,
    large, imminent, confident insight, and that is exactly the thing that
    should sit at the top of the list.
    """
    total = (
        SEVERITY_BASE.get(severity, SEVERITY_BASE[InsightSeverity.INFO])
        + magnitude_points(amount_minor, monthly_baseline_minor)
        + urgency_points(due_on, as_of)
        + confidence_points(confidence)
    )
    return max(0, min(100, total))


def explain_score(
    *,
    severity: str,
    as_of: date,
    amount_minor: int | None = None,
    monthly_baseline_minor: int | None = None,
    due_on: date | None = None,
    confidence: float = 1.0,
) -> dict:
    """The score broken into its parts.

    Exposed so ranking can be justified rather than asserted — the same reason
    every insight carries a rationale. If a user asks why one thing is above
    another, there's an answer.
    """
    return {
        "severity": SEVERITY_BASE.get(severity, SEVERITY_BASE[InsightSeverity.INFO]),
        "magnitude": magnitude_points(amount_minor, monthly_baseline_minor),
        "urgency": urgency_points(due_on, as_of),
        "confidence": confidence_points(confidence),
        "total": score_insight(
            severity=severity,
            as_of=as_of,
            amount_minor=amount_minor,
            monthly_baseline_minor=monthly_baseline_minor,
            due_on=due_on,
            confidence=confidence,
        ),
    }
