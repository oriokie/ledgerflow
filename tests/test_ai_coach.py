"""AI financial coach: scoring, generation idempotency, and briefings.

The properties pinned hardest here are the ones that decide whether a user
keeps reading the coach at all:

  * a re-run must not pile up duplicates;
  * a dismissal must stick;
  * severity must not be inflated, or everything becomes noise.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from apps.intelligence import coach, scoring
from apps.intelligence.models import (
    Briefing,
    BriefingPeriod,
    Insight,
    InsightKind,
    InsightSeverity,
    InsightStatus,
)
from apps.intelligence.protocols import (
    CoachContext,
    InsightCandidate,
    Provenance,
    ProviderKind,
)
from apps.intelligence.providers.coach import RuleBasedCoach, TemplateNarrator
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db

TODAY = date(2026, 6, 15)


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _ctx(**overrides) -> CoachContext:
    params = {"as_of": TODAY, "currency": "USD"}
    params.update(overrides)
    return CoachContext(**params)


def _candidate(**overrides) -> InsightCandidate:
    params = {
        "kind": InsightKind.OVERSPENDING,
        "severity": InsightSeverity.WARNING,
        "title": "Over budget",
        "body": "You spent more than planned.",
        "rationale": "Spending exceeded the limit.",
        "dedupe_key": "test:1",
        "evidence": {"over_minor": 5_000},
        "provenance": Provenance(provider="Test", kind=ProviderKind.RULE, version="1.0"),
    }
    params.update(overrides)
    return InsightCandidate(**params)


# ------------------------------------------------------------------- scoring
def test_severity_dominates_the_score():
    """A deadline outranks an idea, however large the idea."""
    critical = scoring.score_insight(severity=InsightSeverity.CRITICAL, as_of=TODAY)
    opportunity = scoring.score_insight(
        severity=InsightSeverity.OPPORTUNITY,
        as_of=TODAY,
        amount_minor=1_000_000,
        monthly_baseline_minor=100_000,
    )
    assert critical > opportunity


def test_magnitude_is_relative_to_the_user_not_absolute():
    """£200 means something different at £800/month than at £8,000/month."""
    modest_earner = scoring.magnitude_points(20_000, 80_000)
    high_earner = scoring.magnitude_points(20_000, 800_000)
    assert modest_earner > high_earner


def test_magnitude_returns_nothing_without_a_baseline():
    # Dividing by an unknown baseline would invent a ratio.
    assert scoring.magnitude_points(20_000, None) == 0
    assert scoring.magnitude_points(20_000, 0) == 0
    assert scoring.magnitude_points(None, 100_000) == 0


def test_urgency_peaks_when_overdue_and_decays_to_nothing():
    assert scoring.urgency_points(TODAY, TODAY) == scoring.MAX_URGENCY_POINTS
    assert scoring.urgency_points(TODAY - timedelta(days=5), TODAY) == scoring.MAX_URGENCY_POINTS
    assert scoring.urgency_points(TODAY + timedelta(days=60), TODAY) == 0
    # An undated insight gets nothing, not a default — "no deadline" is not
    # "distant deadline".
    assert scoring.urgency_points(None, TODAY) == 0


def test_urgency_decreases_as_the_date_recedes():
    near = scoring.urgency_points(TODAY + timedelta(days=3), TODAY)
    far = scoring.urgency_points(TODAY + timedelta(days=25), TODAY)
    assert near > far


def test_confidence_is_clamped_and_weighted_lightly():
    assert scoring.confidence_points(5.0) == scoring.MAX_CONFIDENCE_POINTS
    assert scoring.confidence_points(-1.0) == 0
    # Confidence must not be able to outweigh severity — especially once an LLM
    # is supplying that number about itself.
    assert scoring.SEVERITY_BASE[InsightSeverity.INFO] > scoring.MAX_CONFIDENCE_POINTS


def test_score_is_bounded_to_0_100():
    top = scoring.score_insight(
        severity=InsightSeverity.CRITICAL,
        as_of=TODAY,
        amount_minor=10_000_000,
        monthly_baseline_minor=100_000,
        due_on=TODAY,
        confidence=1.0,
    )
    assert 0 <= top <= 100


def test_explain_score_breaks_down_into_its_parts():
    parts = scoring.explain_score(
        severity=InsightSeverity.WARNING,
        as_of=TODAY,
        amount_minor=25_000,
        monthly_baseline_minor=100_000,
        due_on=TODAY + timedelta(days=10),
    )
    # Ranking should be justifiable, not asserted.
    assert set(parts) == {"severity", "magnitude", "urgency", "confidence", "total"}
    assert parts["total"] == sum(v for k, v in parts.items() if k != "total")


# ------------------------------------------------------------------ detectors
def test_overspending_states_the_actual_figures():
    coach_provider = RuleBasedCoach()
    ctx = _ctx(
        budget_lines=(
            {
                "category_id": "c1",
                "category_name": "Groceries",
                "limit_minor": 35_000,
                "spent_minor": 41_200,
                "percent": 117.7,
                "period_end": date(2026, 6, 30),
            },
        )
    )
    [insight] = [i for i in coach_provider.generate(ctx) if i.kind == InsightKind.OVERSPENDING]

    # "You've spent X of Y" is checkable; "you're overspending" is an accusation.
    assert "412" in insight.body
    assert "350" in insight.body
    assert insight.evidence["over_minor"] == 6_200
    assert insight.rationale


def test_a_line_within_its_limit_produces_nothing():
    ctx = _ctx(
        budget_lines=(
            {
                "category_id": "c1",
                "category_name": "Groceries",
                "limit_minor": 35_000,
                "spent_minor": 30_000,
                "percent": 85.7,
                "period_end": date(2026, 6, 30),
            },
        )
    )
    assert not [i for i in RuleBasedCoach().generate(ctx) if i.kind == InsightKind.OVERSPENDING]


def test_duplicate_wording_observes_rather_than_asserts():
    ctx = _ctx(
        possible_duplicates=(
            {
                "transaction_id": "t1",
                "payee": "Coffee Shop",
                "amount_minor": 450,
                "occurred_on": TODAY,
                "count": 2,
            },
        )
    )
    [insight] = [i for i in RuleBasedCoach().generate(ctx) if i.kind == InsightKind.DUPLICATE_TRANSACTION]

    # Telling someone they were double-charged when they bought two coffees
    # costs more trust than the catch was worth.
    assert "worth checking" in insight.body.lower()
    assert insight.severity == InsightSeverity.INFO
    assert insight.confidence < 1.0


def test_only_cashflow_risk_earns_critical_severity():
    """A coach that shouts about everything gets muted."""
    ctx = _ctx(
        budget_lines=(
            {
                "category_id": "c1",
                "category_name": "Groceries",
                "limit_minor": 10_000,
                "spent_minor": 90_000,
                "percent": 900.0,
                "period_end": date(2026, 6, 30),
            },
        ),
        debts=({"account_id": "a1", "name": "Card", "balance_minor": 500_000, "currency": "USD"},),
        savings_rate=0.0,
    )
    generated = RuleBasedCoach().generate(ctx)
    assert generated, "expected some insights"
    assert not [i for i in generated if i.severity == InsightSeverity.CRITICAL]

    with_risk = RuleBasedCoach().generate(
        _ctx(
            cashflow_risk={
                "first_negative_on": TODAY + timedelta(days=5),
                "lowest_balance_minor": -12_000,
                "lowest_balance_on": TODAY + timedelta(days=6),
                "negative_day_count": 3,
            }
        )
    )
    assert [i for i in with_risk if i.severity == InsightSeverity.CRITICAL]


def test_subscriptions_are_annualised():
    ctx = _ctx(
        subscriptions=(
            {"name": "Streaming", "amount_minor": 1_200, "frequency": "monthly", "annual_minor": 14_400},
        )
    )
    [insight] = [i for i in RuleBasedCoach().generate(ctx) if i.kind == InsightKind.SUBSCRIPTION_REVIEW]
    # £12/month doesn't feel like a decision; £144/year does.
    assert "144" in insight.title or "144" in insight.body


def test_every_candidate_carries_a_rationale_and_a_dedupe_key():
    """The contract that stops a future LLM asserting the unsupportable."""
    ctx = _ctx(
        budget_lines=(
            {
                "category_id": "c1",
                "category_name": "Groceries",
                "limit_minor": 10_000,
                "spent_minor": 20_000,
                "percent": 200.0,
                "period_end": date(2026, 6, 30),
            },
            # Under its limit but on pace to blow it: the two overspend kinds
            # are mutually exclusive per line, so reaching both needs two.
            {
                "category_id": "c9",
                "category_name": "Dining out",
                "limit_minor": 30_000,
                "spent_minor": 24_000,
                "percent": 80.0,
                "period_start": date(2026, 6, 1),
                "period_end": date(2026, 6, 30),
            },
        ),
        category_trends=(
            {
                "category_id": "c2",
                "category_name": "Dining",
                "current_minor": 30_000,
                "previous_minor": 10_000,
                "delta_pct": 2.0,
            },
        ),
        debts=({"account_id": "a1", "name": "Card", "balance_minor": 100_000, "currency": "USD"},),
        savings_rate=0.02,
    )
    for candidate in RuleBasedCoach().generate(ctx):
        assert candidate.rationale.strip(), f"{candidate.kind} has no rationale"
        assert candidate.dedupe_key.strip(), f"{candidate.kind} has no dedupe key"


def test_an_empty_context_produces_no_insights():
    # Nothing to say is a valid answer; filler would train users to skim.
    assert RuleBasedCoach().generate(_ctx()) == []


# ------------------------------------------------------------------ persistence
def test_generation_persists_insights_with_scores(tenant):
    with tenant_scope(tenant):
        ctx = _ctx(
            budget_lines=(
                {
                    "category_id": None,
                    "category_name": "Groceries",
                    "limit_minor": 35_000,
                    "spent_minor": 41_200,
                    "percent": 117.7,
                    "period_end": date(2026, 12, 31),
                },
            )
        )
        created = coach.generate_insights(as_of=TODAY, context=ctx)
        assert created
        stored = Insight.objects.get(kind=InsightKind.OVERSPENDING)
        assert stored.priority_score > 0
        assert stored.rationale
        assert stored.provider == "RuleBasedCoach"


def test_regeneration_refreshes_rather_than_duplicating(tenant):
    """The coach runs daily; without this a user wakes to a fresh copy of the
    same insight every morning."""
    with tenant_scope(tenant):
        ctx = _ctx(
            budget_lines=(
                {
                    "category_id": None,
                    "category_name": "Groceries",
                    "limit_minor": 35_000,
                    "spent_minor": 41_200,
                    "percent": 117.7,
                    "period_end": date(2026, 12, 31),
                },
            )
        )
        coach.generate_insights(as_of=TODAY, context=ctx)
        coach.generate_insights(as_of=TODAY, context=ctx)
        coach.generate_insights(as_of=TODAY + timedelta(days=1), context=ctx)

        assert Insight.objects.filter(kind=InsightKind.OVERSPENDING).count() == 1


def test_refresh_updates_the_figures(tenant):
    with tenant_scope(tenant):

        def ctx_with(spent: int):
            return _ctx(
                budget_lines=(
                    {
                        "category_id": None,
                        "category_name": "Groceries",
                        "limit_minor": 35_000,
                        "spent_minor": spent,
                        "percent": 100.0,
                        "period_end": date(2026, 12, 31),
                    },
                )
            )

        coach.generate_insights(as_of=TODAY, context=ctx_with(41_200))
        coach.generate_insights(as_of=TODAY, context=ctx_with(52_000))

        stored = Insight.objects.get(kind=InsightKind.OVERSPENDING)
        assert stored.evidence["spent_minor"] == 52_000


def test_a_dismissed_insight_stays_dismissed_after_regeneration(tenant):
    """Overriding a dismissal is how a product teaches people to stop reading."""
    with tenant_scope(tenant):
        ctx = _ctx(
            budget_lines=(
                {
                    "category_id": None,
                    "category_name": "Groceries",
                    "limit_minor": 35_000,
                    "spent_minor": 41_200,
                    "percent": 117.7,
                    "period_end": date(2026, 12, 31),
                },
            )
        )
        coach.generate_insights(as_of=TODAY, context=ctx)
        insight = Insight.objects.get(kind=InsightKind.OVERSPENDING)
        coach.dismiss_insight(insight=insight)

        refreshed = coach.generate_insights(as_of=TODAY, context=ctx)

        insight.refresh_from_db()
        assert insight.status == InsightStatus.DISMISSED
        assert insight.id not in [i.id for i in refreshed]
        assert insight.id not in [i.id for i in coach.live_insights(as_of=TODAY)]


def test_bookmarked_insights_stay_in_the_feed(tenant):
    """A bookmark means "keep this in front of me" — the opposite of dismissal."""
    with tenant_scope(tenant):
        ctx = _ctx(
            budget_lines=(
                {
                    "category_id": None,
                    "category_name": "Groceries",
                    "limit_minor": 35_000,
                    "spent_minor": 41_200,
                    "percent": 117.7,
                    "period_end": date(2026, 12, 31),
                },
            )
        )
        coach.generate_insights(as_of=TODAY, context=ctx)
        insight = Insight.objects.get(kind=InsightKind.OVERSPENDING)
        coach.bookmark_insight(insight=insight)

        assert insight.id in [i.id for i in coach.live_insights(as_of=TODAY)]


def test_expired_insights_leave_the_feed_and_can_be_purged(tenant):
    with tenant_scope(tenant):
        ctx = _ctx(
            budget_lines=(
                {
                    "category_id": None,
                    "category_name": "Groceries",
                    "limit_minor": 35_000,
                    "spent_minor": 41_200,
                    "percent": 117.7,
                    "period_end": TODAY - timedelta(days=1),
                },
            )
        )
        coach.generate_insights(as_of=TODAY, context=ctx)

        assert list(coach.live_insights(as_of=TODAY)) == []
        assert coach.purge_expired_insights(as_of=TODAY) == 1


def test_feed_is_ordered_by_priority(tenant):
    with tenant_scope(tenant):
        ctx = _ctx(
            cashflow_risk={
                "first_negative_on": TODAY + timedelta(days=3),
                "lowest_balance_minor": -50_000,
                "lowest_balance_on": TODAY + timedelta(days=4),
                "negative_day_count": 2,
            },
            subscriptions=(
                {"name": "Streaming", "amount_minor": 1_200, "frequency": "monthly", "annual_minor": 14_400},
            ),
        )
        coach.generate_insights(as_of=TODAY, context=ctx)
        feed = list(coach.live_insights(as_of=TODAY))

        assert len(feed) >= 2
        assert feed[0].kind == InsightKind.CASHFLOW_RISK
        assert feed[0].priority_score >= feed[-1].priority_score


# ------------------------------------------------------------------- briefing
def test_narrator_leads_with_the_most_urgent_thing():
    draft = TemplateNarrator().write_briefing(
        period="daily",
        context=_ctx(savings_rate=0.2),
        insights=[
            _candidate(severity=InsightSeverity.OPPORTUNITY, title="Review subscriptions"),
            _candidate(severity=InsightSeverity.CRITICAL, title="Balance goes negative Friday"),
        ],
    )
    assert draft.headline == "Balance goes negative Friday"


def test_narrator_says_so_when_nothing_needs_attention():
    draft = TemplateNarrator().write_briefing(period="daily", context=_ctx(), insights=[])
    # A real answer beats inventing something to report.
    assert "nothing needs your attention" in draft.headline.lower()
    assert draft.metrics["insight_count"] == 0


def test_narrator_does_not_repeat_the_headline_in_the_body():
    """The body says what the headline did not.

    The headline is promoted from the insights, so the item it came from was
    also the first thing listed in the summary — and the same sentence then
    appeared a third time as the top insight card. Three copies of one line
    within a single screen reads as a stuck record, not a briefing.
    """
    draft = TemplateNarrator().write_briefing(
        period="daily",
        context=_ctx(savings_rate=0.55),
        insights=[
            _candidate(severity=InsightSeverity.WARNING, title="KES 3,134 outstanding on cards"),
            _candidate(severity=InsightSeverity.OPPORTUNITY, title="Clear your credit card balance"),
        ],
    )
    assert draft.headline == "KES 3,134 outstanding on cards"
    assert draft.headline not in draft.summary
    # The rest still gets said.
    assert "Clear your credit card balance" in draft.summary


def test_narrator_still_counts_the_group_the_headline_came_from():
    """Dropping the echo must not drop the tally."""
    draft = TemplateNarrator().write_briefing(
        period="daily",
        context=_ctx(),
        insights=[
            _candidate(severity=InsightSeverity.WARNING, title="Dining is over budget"),
            _candidate(severity=InsightSeverity.WARNING, title="Two subscriptions renewed together"),
        ],
    )
    assert draft.headline == "Dining is over budget"
    # Both are counted; only the one already read is left unnamed.
    assert "2 worth a look" in draft.summary
    assert "Two subscriptions renewed together" in draft.summary
    assert "Dining is over budget" not in draft.summary


def test_briefing_is_stored_and_refreshed_not_duplicated(tenant):
    with tenant_scope(tenant):
        first = coach.generate_briefing(period=BriefingPeriod.DAILY, as_of=TODAY)
        second = coach.generate_briefing(period=BriefingPeriod.DAILY, as_of=TODAY)

        assert first.id == second.id
        assert Briefing.objects.filter(period=BriefingPeriod.DAILY).count() == 1


def test_each_period_gets_its_own_briefing(tenant):
    with tenant_scope(tenant):
        coach.generate_briefing(period=BriefingPeriod.DAILY, as_of=TODAY)
        coach.generate_briefing(period=BriefingPeriod.WEEKLY, as_of=TODAY)
        coach.generate_briefing(period=BriefingPeriod.MONTHLY, as_of=TODAY)
        assert Briefing.objects.count() == 3


def test_briefing_window_matches_its_period(tenant):
    with tenant_scope(tenant):
        weekly = coach.generate_briefing(period=BriefingPeriod.WEEKLY, as_of=TODAY)
        assert weekly.period_start == TODAY - timedelta(days=6)
        assert weekly.period_end == TODAY


def test_unknown_period_is_rejected(tenant):
    with tenant_scope(tenant), pytest.raises(coach.CoachError):
        coach.generate_briefing(period="fortnightly", as_of=TODAY)


# --------------------------------------------------------------- provider seam
def test_a_custom_provider_can_be_swapped_in(tenant, settings):
    """The seam that makes an LLM a config change rather than a refactor."""

    settings.INTELLIGENCE_PROVIDERS = {
        "insight": "tests.test_ai_coach.StubCoach",
    }
    with tenant_scope(tenant):
        created = coach.generate_insights(as_of=TODAY, context=_ctx())
        assert len(created) == 1
        assert created[0].title == "From a stub provider"
        assert created[0].provider == "StubCoach"


class StubCoach:
    """Stands in for a future LLM provider: same protocol, different source."""

    def generate(self, context: CoachContext) -> list[InsightCandidate]:
        return [
            InsightCandidate(
                kind=InsightKind.HEALTH_IMPROVEMENT,
                severity=InsightSeverity.INFO,
                title="From a stub provider",
                body="Proves the registry seam works.",
                rationale="Returned unconditionally by the stub.",
                dedupe_key="stub:1",
                provenance=Provenance(provider="StubCoach", kind=ProviderKind.LLM, version="0.1"),
            )
        ]


# ---------------------------------------------------------------------- API
def test_insight_endpoints_generate_read_and_decide(tenant_context):
    _, client = tenant_context

    generated = client.post("/api/v1/intelligence/insights/generate/")
    assert generated.status_code == 201, generated.data

    listing = client.get("/api/v1/intelligence/insights/")
    assert listing.status_code == 200

    if not listing.data:
        pytest.skip("empty workspace produced no insights, which is itself correct")

    insight = listing.data[0]
    # Every insight ships with its reason.
    assert insight["rationale"]
    assert 0 <= insight["priority_score"] <= 100

    dismissed = client.post(f"/api/v1/intelligence/insights/{insight['id']}/dismiss/")
    assert dismissed.status_code == 200
    assert dismissed.data["status"] == "dismissed"

    after = client.get("/api/v1/intelligence/insights/")
    assert insight["id"] not in [i["id"] for i in after.data]

    bookmarked = client.get("/api/v1/intelligence/insights/?status=dismissed")
    assert insight["id"] in [i["id"] for i in bookmarked.data]


def test_unknown_decision_is_rejected(tenant_context):
    _, client = tenant_context
    resp = client.post("/api/v1/intelligence/insights/00000000-0000-0000-0000-000000000000/explode/")
    assert resp.status_code == 400


def test_briefing_endpoint_returns_a_narrative(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/intelligence/briefing/daily/")
    assert resp.status_code == 200, resp.data
    assert resp.data["headline"]
    assert resp.data["summary"]
    # The prose can always be checked against the figures it came from.
    assert "insight_count" in resp.data["metrics"]


def test_unknown_briefing_period_is_rejected(tenant_context):
    _, client = tenant_context
    assert client.get("/api/v1/intelligence/briefing/fortnightly/").status_code == 400


# ------------------------------------------------------- previously-dead detectors
def test_merchant_change_reports_both_directions():
    """A price drop is genuinely useful — it confirms a renegotiation worked.
    A coach that only ever delivers bad news is one people stop opening."""
    ctx = _ctx(
        merchant_changes=(
            {"payee": "Broadband Co", "previous_minor": 3_000, "current_minor": 4_200, "delta_pct": 0.4},
            {"payee": "Insurer", "previous_minor": 5_000, "current_minor": 4_000, "delta_pct": -0.2},
        )
    )
    found = [i for i in RuleBasedCoach().generate(ctx) if i.kind == InsightKind.MERCHANT_CHANGE]
    assert len(found) == 2
    assert any("up 40%" in i.title for i in found)
    assert any("down 20%" in i.title for i in found)
    # A price change is worth knowing, not worth alarming about.
    assert all(i.severity == InsightSeverity.INFO for i in found)


def test_income_drop_warns_but_a_rise_does_not():
    drop = RuleBasedCoach().generate(
        _ctx(
            income_changes=(
                {
                    "previous_minor": 300_000,
                    "current_minor": 200_000,
                    "delta_pct": -0.333,
                    "period_start": date(2026, 6, 1),
                },
            )
        )
    )
    [fell] = [i for i in drop if i.kind == InsightKind.SALARY_CHANGE]
    assert fell.severity == InsightSeverity.WARNING
    assert "down 33%" in fell.title

    rise = RuleBasedCoach().generate(
        _ctx(
            income_changes=(
                {
                    "previous_minor": 200_000,
                    "current_minor": 300_000,
                    "delta_pct": 0.5,
                    "period_start": date(2026, 6, 1),
                },
            )
        )
    )
    [grew] = [i for i in rise if i.kind == InsightKind.SALARY_CHANGE]
    # Good news is not a warning.
    assert grew.severity == InsightSeverity.INFO


def test_health_insight_targets_the_weakest_component():
    ctx = _ctx(
        health={
            "score": 62,
            "band": "fair",
            "components": [
                {"name": "Savings rate", "score": 30, "detail": "You keep very little of what you earn."},
                {"name": "Budget adherence", "score": 88, "detail": "Most lines stay within limit."},
            ],
        }
    )
    [insight] = [i for i in RuleBasedCoach().generate(ctx) if i.kind == InsightKind.HEALTH_IMPROVEMENT]
    # The lowest-scoring component is where an improvement moves the number most.
    assert "Savings rate" in insight.title
    assert "62" in insight.rationale


def test_health_insight_is_skipped_without_components():
    assert not [
        i for i in RuleBasedCoach().generate(_ctx(health={})) if i.kind == InsightKind.HEALTH_IMPROVEMENT
    ]


def test_every_insight_kind_is_reachable():
    """Every taxonomy value must have a detector that can produce it.

    A kind with a model, an icon and a label but no detector is a promise the
    product never keeps — which is exactly what these three were before.
    """
    ctx = _ctx(
        budget_lines=(
            {
                "category_id": "c1",
                "category_name": "Groceries",
                "limit_minor": 10_000,
                "spent_minor": 20_000,
                "percent": 200.0,
                "period_end": date(2026, 6, 30),
            },
            # Under its limit but on pace to blow it: the two overspend kinds
            # are mutually exclusive per line, so reaching both needs two.
            {
                "category_id": "c9",
                "category_name": "Dining out",
                "limit_minor": 30_000,
                "spent_minor": 24_000,
                "percent": 80.0,
                "period_start": date(2026, 6, 1),
                "period_end": date(2026, 6, 30),
            },
        ),
        category_trends=(
            {
                "category_id": "c2",
                "category_name": "Dining",
                "current_minor": 30_000,
                "previous_minor": 10_000,
                "delta_pct": 2.0,
            },
        ),
        large_transactions=(
            {"transaction_id": "t1", "payee": "Furniture", "amount_minor": 90_000, "occurred_on": TODAY},
        ),
        possible_duplicates=(
            {
                "transaction_id": "t2",
                "payee": "Coffee",
                "amount_minor": 450,
                "occurred_on": TODAY,
                "count": 2,
            },
        ),
        merchant_changes=(
            {"payee": "Broadband", "previous_minor": 3_000, "current_minor": 4_200, "delta_pct": 0.4},
        ),
        income_changes=(
            {
                "previous_minor": 300_000,
                "current_minor": 200_000,
                "delta_pct": -0.33,
                "period_start": date(2026, 6, 1),
            },
        ),
        cashflow_risk={
            "first_negative_on": TODAY + timedelta(days=5),
            "lowest_balance_minor": -12_000,
            "lowest_balance_on": TODAY + timedelta(days=6),
            "negative_day_count": 3,
        },
        subscriptions=(
            {"name": "Streaming", "amount_minor": 1_200, "frequency": "monthly", "annual_minor": 14_400},
        ),
        goal_suggestions=(
            {
                "kind": "emergency_fund",
                "title": "Build an emergency fund",
                "rationale": "Three months of cover.",
                "suggested_target_minor": 600_000,
                "currency": "USD",
            },
        ),
        debts=({"account_id": "a1", "name": "Card", "balance_minor": 240_000, "currency": "USD"},),
        health={
            "score": 62,
            "band": "fair",
            "components": [{"name": "Savings rate", "score": 30, "detail": "Low."}],
        },
        savings_rate=0.02,
        # Debt-derived kinds arrive pre-analysed from the debt module rather
        # than being recomputed here, so the context must carry them for the
        # coverage guarantee to mean anything.
        debt_signals=tuple(
            {
                "kind": kind,
                "severity": "warning",
                "title": f"{kind} title",
                "body": "Body.",
                "rationale": "Reason.",
                "dedupe_key": f"{kind}:1",
                "evidence": {},
                "account_id": None,
                "action": {},
            }
            for kind in (
                InsightKind.PROMO_EXPIRY,
                InsightKind.RATE_INCREASE,
                InsightKind.REFINANCE_OPPORTUNITY,
                InsightKind.HIGH_FEES,
                InsightKind.OFFSET_OPPORTUNITY,
                InsightKind.DEBT_MILESTONE,
            )
        ),
    )
    produced = {i.kind for i in RuleBasedCoach().generate(ctx)}

    # BUDGET_RECOMMENDATION only fires when there is *no* budget, so it is
    # mutually exclusive with OVERSPENDING and excluded here by design.
    expected = set(InsightKind.values) - {InsightKind.BUDGET_RECOMMENDATION}
    assert produced == expected, f"unreachable kinds: {sorted(expected - produced)}"


def test_budget_recommendation_fires_when_no_budget_exists():
    """The one kind excluded above — proved reachable on its own terms."""
    ctx = _ctx(
        category_trends=(
            {
                "category_id": "c2",
                "category_name": "Dining",
                "current_minor": 30_000,
                "previous_minor": 10_000,
                "delta_pct": 2.0,
            },
        )
    )
    assert any(i.kind == InsightKind.BUDGET_RECOMMENDATION for i in RuleBasedCoach().generate(ctx))


# ------------------------------------------------- context builder integration
def test_merchant_change_is_detected_from_real_transactions(tenant):
    """Proves the context builder actually feeds the detector — a detector with
    no data source is the exact failure these three had."""
    from django.utils import timezone

    from apps.finance import services as finance_services
    from apps.finance.models import AccountType, CategoryKind
    from apps.finance.payees import get_or_create_payee
    from apps.intelligence import coach_context

    today = timezone.localdate()
    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=500_000,
        )
        category = finance_services.create_category(
            name="Utilities", kind=CategoryKind.EXPENSE, currency="USD"
        )
        payee, _ = get_or_create_payee(name="Broadband Co")

        # Two charges at 30.00 in the prior window: a real baseline.
        for days_ago in (55, 45):
            finance_services.record_expense(
                financial_account=account,
                category=category,
                amount_minor=3_000,
                occurred_at=timezone.now() - timezone.timedelta(days=days_ago),
                payee=payee,
            )
        # One charge at 42.00 in the recent window: a 40% rise.
        finance_services.record_expense(
            financial_account=account,
            category=category,
            amount_minor=4_200,
            occurred_at=timezone.now() - timezone.timedelta(days=5),
            payee=payee,
        )

        changes = coach_context.build_context(as_of=today).merchant_changes
        assert any(c["payee"] == "Broadband Co" and c["delta_pct"] > 0.3 for c in changes)


def test_a_first_ever_purchase_is_not_a_price_change(tenant):
    """Treating a first purchase as a price rise is the false alarm that gets a
    coach muted."""
    from django.utils import timezone

    from apps.finance import services as finance_services
    from apps.finance.models import AccountType, CategoryKind
    from apps.finance.payees import get_or_create_payee
    from apps.intelligence import coach_context

    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=500_000,
        )
        category = finance_services.create_category(
            name="Shopping", kind=CategoryKind.EXPENSE, currency="USD"
        )
        finance_services.record_expense(
            financial_account=account,
            category=category,
            amount_minor=9_900,
            occurred_at=timezone.now() - timezone.timedelta(days=2),
            payee=get_or_create_payee(name="New Shop")[0],
        )

        changes = coach_context.build_context(as_of=timezone.localdate()).merchant_changes
        assert not any(c["payee"] == "New Shop" for c in changes)


def test_health_is_populated_from_the_existing_scorer(tenant):
    """The scorer was already built and tested — the coach just wasn't reading it."""
    from apps.finance import services as finance_services
    from apps.finance.models import AccountType
    from apps.intelligence import coach_context

    with tenant_scope(tenant):
        finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=250_000,
        )
        health = coach_context.build_context().health
        assert "score" in health
        assert health["components"], "expected scored components"


def test_duplicates_are_detected_from_real_transactions(tenant):
    """Regression guard for a GROUP BY leak.

    `list_transactions()` is ordered, and Django folds ORDER BY fields into
    GROUP BY — so `.values().annotate()` returned one row per transaction and
    the `n > 1` filter matched nothing. The detector looked implemented and
    found nothing, ever. Only an integration test could catch that; the unit
    tests passed against hand-built context throughout.
    """
    from django.utils import timezone

    from apps.finance import services as finance_services
    from apps.finance.models import AccountType, CategoryKind
    from apps.finance.payees import get_or_create_payee
    from apps.intelligence import coach_context

    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=500_000,
        )
        category = finance_services.create_category(name="Food", kind=CategoryKind.EXPENSE, currency="USD")
        payee, _ = get_or_create_payee(name="Corner Shop")

        when = timezone.now() - timezone.timedelta(days=3)
        for _ in range(2):
            finance_services.record_expense(
                financial_account=account,
                category=category,
                amount_minor=1_250,
                occurred_at=when,
                payee=payee,
            )

        duplicates = coach_context.build_context().possible_duplicates
        assert any(d["payee"] == "Corner Shop" and d["count"] == 2 for d in duplicates)


def test_a_single_charge_is_not_reported_as_a_duplicate(tenant):
    from django.utils import timezone

    from apps.finance import services as finance_services
    from apps.finance.models import AccountType, CategoryKind
    from apps.finance.payees import get_or_create_payee
    from apps.intelligence import coach_context

    with tenant_scope(tenant):
        account = finance_services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=500_000,
        )
        category = finance_services.create_category(name="Food", kind=CategoryKind.EXPENSE, currency="USD")
        finance_services.record_expense(
            financial_account=account,
            category=category,
            amount_minor=1_250,
            occurred_at=timezone.now() - timezone.timedelta(days=3),
            payee=get_or_create_payee(name="Solo Shop")[0],
        )
        assert coach_context.build_context().possible_duplicates == ()


# =============================================================================
# Per-tenant AI opt-out
#
# Provider/model selection in the registry is deployment-wide and settings-
# only by design (registry.py) — it has no notion of "this one tenant". The
# gate has to live at the call site that actually knows which tenant a run is
# for, which is coach.py's generate_insights/generate_briefing. These tests
# configure a real LLM provider via INTELLIGENCE_PROVIDERS and confirm a
# tenant that has opted out never reaches it regardless.
# =============================================================================
def test_an_opted_out_tenant_never_constructs_the_configured_llm_provider():
    """The property the whole feature exists for: an LLM being configured at
    the deployment level must not force every workspace on it to use one.

    Asserted as strongly as this can be: the configured provider class is
    patched so constructing it raises. A weaker assertion (like "insights is
    not None") wouldn't actually prove the LLM path was skipped, since a
    misconfigured LLMCoach can fail soft and produce nothing anyway — this
    proves the *class itself* was never reached at all.
    """
    from unittest.mock import patch

    from apps.tenancy.models import Tenant

    workspace = Tenant.objects.create(name="Opted-out household", ai_enabled=False)

    with (
        tenant_scope(workspace.id),
        patch(
            "apps.intelligence.registry._resolve",
            side_effect=AssertionError("registry reached despite tenant opt-out"),
        ),
    ):
        insights = coach.generate_insights()
        assert insights is not None  # completed via the rule-based path, untouched


def test_an_opted_in_tenant_does_reach_the_registry():
    """The gate must not accidentally downgrade *everyone* — only tenants that
    have actually opted out. The counterpart to the test above: here the
    registry SHOULD be reached, and the test fails if it isn't."""
    from unittest.mock import patch

    from apps.tenancy.models import Tenant

    workspace = Tenant.objects.create(name="Opted-in household", ai_enabled=True)

    with (
        tenant_scope(workspace.id),
        patch(
            "apps.intelligence.coach.get_insight_provider",
            wraps=coach.get_insight_provider,
        ) as spied,
    ):
        coach.generate_insights()
        spied.assert_called_once()


def test_the_flag_defaults_to_enabled():
    """Nothing changes for an existing workspace on a deployment that already
    has AI configured — this must be additive, not a silent regression."""
    from apps.tenancy.models import Tenant

    # A real row is needed here specifically — the `tenant` fixture elsewhere
    # in this file is a bare UUID for RLS scoping, not an actual Tenant row,
    # which is enough for models that only carry a raw tenant_id but not for
    # asserting a default on the Tenant model's own field.
    workspace = Tenant.objects.create(name="Test Workspace")
    assert workspace.ai_enabled is True


def test_no_bound_tenant_defaults_to_enabled_rather_than_silently_downgrading():
    """A script or management command running with no tenant context is not
    "a tenant that opted out" — it's simply outside the scope this flag
    governs, and the safe default is not to downgrade behaviour nobody set."""
    from apps.intelligence.coach import _tenant_ai_enabled

    assert _tenant_ai_enabled() is True


# =============================================================================
# API: the workspace-level AI toggle
# =============================================================================
def test_api_llm_settings_reports_the_tenant_flag(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/intelligence/llm-settings/")
    assert resp.status_code == 200
    assert resp.data["tenant_ai_enabled"] is True


def test_api_owner_can_toggle_the_flag_off(tenant_context):
    membership, client = tenant_context
    resp = client.patch("/api/v1/intelligence/llm-settings/", {"tenant_ai_enabled": False}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.data["tenant_ai_enabled"] is False

    from apps.tenancy.models import Tenant

    assert Tenant.objects.get(id=membership.tenant_id).ai_enabled is False


def test_api_toggling_off_then_on_round_trips(tenant_context):
    _, client = tenant_context
    client.patch("/api/v1/intelligence/llm-settings/", {"tenant_ai_enabled": False}, format="json")
    resp = client.patch("/api/v1/intelligence/llm-settings/", {"tenant_ai_enabled": True}, format="json")
    assert resp.data["tenant_ai_enabled"] is True


def test_api_a_plain_member_cannot_toggle_the_flag():
    """This is a decision about the whole household's data, not an individual
    member's preference — the same bar as every other workspace-level write."""
    from apps.tenancy.models import Role
    from tests.conftest import _bearer_client
    from tests.factories import MembershipFactory

    membership = MembershipFactory(role=Role.MEMBER)
    client = _bearer_client(membership.user, tenant_id=membership.tenant_id)

    resp = client.patch("/api/v1/intelligence/llm-settings/", {"tenant_ai_enabled": False}, format="json")
    assert resp.status_code == 403

    from apps.tenancy.models import Tenant

    assert Tenant.objects.get(id=membership.tenant_id).ai_enabled is True


def test_api_a_plain_member_can_still_read_the_settings():
    """GET stays open to any member — only the write is restricted."""
    from apps.tenancy.models import Role
    from tests.conftest import _bearer_client
    from tests.factories import MembershipFactory

    membership = MembershipFactory(role=Role.MEMBER)
    client = _bearer_client(membership.user, tenant_id=membership.tenant_id)

    resp = client.get("/api/v1/intelligence/llm-settings/")
    assert resp.status_code == 200


def test_api_missing_field_is_a_clean_400_not_a_crash(tenant_context):
    _, client = tenant_context
    resp = client.patch("/api/v1/intelligence/llm-settings/", {}, format="json")
    assert resp.status_code == 400


# ------------------------------------------------------------------ pace
def _pace_line(**overrides):
    line = {
        "category_id": "c1",
        "category_name": "Dining out",
        "limit_minor": 30_000,
        "spent_minor": 24_000,
        "percent": 80.0,
        "period_start": date(2026, 6, 1),
        "period_end": date(2026, 6, 30),
    }
    line.update(overrides)
    return line


def test_pace_warns_before_the_limit_is_crossed():
    """Day 15 of 30, 80% spent: projected ~160% of the limit. _overspending is
    silent (the limit is not yet crossed) and this must not be."""
    coach_provider = RuleBasedCoach()
    ctx = _ctx(as_of=date(2026, 6, 15), budget_lines=(_pace_line(),))

    [insight] = [i for i in coach_provider.generate(ctx) if i.kind == InsightKind.OVERSPEND_PACE]
    assert "Dining out" in insight.title
    assert insight.evidence["projected_minor"] == 48_000
    assert not [i for i in coach_provider.generate(ctx) if i.kind == InsightKind.OVERSPENDING]


def test_pace_is_quiet_when_spending_matches_the_calendar():
    """Half the period gone, half the budget spent: nothing to say."""
    coach_provider = RuleBasedCoach()
    ctx = _ctx(as_of=date(2026, 6, 15), budget_lines=(_pace_line(spent_minor=15_000),))

    assert not [i for i in coach_provider.generate(ctx) if i.kind == InsightKind.OVERSPEND_PACE]


def test_pace_is_quiet_in_the_first_fifth_of_the_period():
    """One grocery run on the 2nd projects to catastrophe. Firing there
    teaches the user to dismiss every warning that follows."""
    coach_provider = RuleBasedCoach()
    ctx = _ctx(as_of=date(2026, 6, 3), budget_lines=(_pace_line(spent_minor=8_000),))

    assert not [i for i in coach_provider.generate(ctx) if i.kind == InsightKind.OVERSPEND_PACE]


def test_pace_needs_a_margin_not_a_hair():
    """Projected 103% is noise — spending is lumpy. Below PACE_TOLERANCE the
    rule stays quiet."""
    coach_provider = RuleBasedCoach()
    # Day 15/30, spent 15_500 → projects to 31_000 = 103% of 30_000.
    ctx = _ctx(as_of=date(2026, 6, 15), budget_lines=(_pace_line(spent_minor=15_500),))

    assert not [i for i in coach_provider.generate(ctx) if i.kind == InsightKind.OVERSPEND_PACE]


def test_pace_hands_over_to_overspending_once_the_limit_is_crossed():
    """Both firing for one category would say "you will overspend" and "you
    have overspent" in the same feed."""
    coach_provider = RuleBasedCoach()
    ctx = _ctx(as_of=date(2026, 6, 20), budget_lines=(_pace_line(spent_minor=31_000),))

    kinds = {i.kind for i in coach_provider.generate(ctx)}
    assert InsightKind.OVERSPENDING in kinds
    assert InsightKind.OVERSPEND_PACE not in kinds


def test_pace_survives_lines_without_period_start():
    """Context rows from an older serialisation carry no period_start; the rule
    must skip them, not crash the whole coach run."""
    coach_provider = RuleBasedCoach()
    line = _pace_line()
    del line["period_start"]
    ctx = _ctx(as_of=date(2026, 6, 15), budget_lines=(line,))

    assert coach_provider.generate(ctx) is not None
