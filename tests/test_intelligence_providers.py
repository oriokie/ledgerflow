"""Provider-layer tests — pure, no DB. These verify the SWAPPABLE SEAM: every
provider satisfies its protocol and returns provenance-stamped DTOs, so an LLM
implementation can be dropped in against the same contract."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from apps.intelligence.automation import (
    AutomationError,
    conditions_match,
    evaluate_rules,
    validate_actions,
)
from apps.intelligence.protocols import (
    AmountObservation,
    AnomalyKind,
    AnomalyProvider,
    CashflowPoint,
    CategorizationProvider,
    ForecastProvider,
    HealthInputs,
    HealthScoreProvider,
    RecommendationContext,
    RecommendationProvider,
    TransactionFeatures,
)
from apps.intelligence.providers.health import WEIGHTS, WeightedHealthScorer
from apps.intelligence.providers.recommend import HeuristicRecommender
from apps.intelligence.providers.rules import RuleBasedCategorizer
from apps.intelligence.providers.statistical import (
    MovingAverageForecaster,
    StatisticalAnomalyDetector,
)


def _features(payee="", memo="", amount=-1000, recent=()):
    return TransactionFeatures(
        payee_normalized=payee,
        memo=memo,
        amount_minor=amount,
        currency="USD",
        occurred_at=datetime(2026, 7, 1, tzinfo=UTC),
        account_type="checking",
        recent_category_ids_for_payee=recent,
    )


# --------------------------------------------------------------- categorizer
def test_categorizer_satisfies_protocol():
    assert isinstance(RuleBasedCategorizer(), CategorizationProvider)


def test_merchant_memory_takes_priority():
    c = RuleBasedCategorizer()
    result = c.suggest_category(_features(payee="whole foods", recent=("cat-groceries",)))
    assert result.category_id == "cat-groceries"
    assert result.confidence >= 0.9
    assert result.provenance.provider == "RuleBasedCategorizer"


def test_keyword_rule_matches_first_time_payee():
    c = RuleBasedCategorizer()
    result = c.suggest_category(_features(payee="blue bottle coffee"))
    assert result.category_id == "dining_out"
    assert 0 < result.confidence < 0.9
    assert "coffee" in result.provenance.rationale.lower()


def test_longest_keyword_wins():
    c = RuleBasedCategorizer(keyword_rules={"gas": "transport", "gas station market": "groceries"})
    # both 'gas' and 'gas station market' present; longer, more specific wins
    result = c.suggest_category(_features(payee="shell gas station market"))
    assert result.category_id == "groceries"


def test_categorizer_abstains_without_signal():
    c = RuleBasedCategorizer()
    result = c.suggest_category(_features(payee="zzz unknown vendor"))
    assert result.category_id is None
    assert result.confidence == 0.0


def test_categorizer_maps_slug_to_real_id():
    c = RuleBasedCategorizer(slug_to_id={"dining_out": "real-uuid-123"})
    result = c.suggest_category(_features(payee="corner cafe"))
    assert result.category_id == "real-uuid-123"


# --------------------------------------------------------------- forecaster
def test_forecaster_satisfies_protocol():
    assert isinstance(MovingAverageForecaster(), ForecastProvider)


def test_forecast_projects_trailing_average():
    history = [
        CashflowPoint(date(2026, 4, 1), 500000, 300000),
        CashflowPoint(date(2026, 5, 1), 500000, 320000),
        CashflowPoint(date(2026, 6, 1), 500000, 340000),
    ]
    forecast = MovingAverageForecaster(window=3).forecast_expense(history, periods_ahead=2)
    assert len(forecast.points) == 2
    # mean of 300k,320k,340k = 320k
    assert forecast.points[0].projected_expense_minor == 320000
    assert forecast.points[0].low_minor <= 320000 <= forecast.points[0].high_minor
    assert forecast.points[0].period_start == date(2026, 7, 1)
    assert forecast.points[1].period_start == date(2026, 8, 1)


def test_forecast_handles_empty_history():
    forecast = MovingAverageForecaster().forecast_expense([], periods_ahead=1)
    assert forecast.points[0].projected_expense_minor == 0


# --------------------------------------------------------------- health
def test_health_scorer_satisfies_protocol():
    assert isinstance(WeightedHealthScorer(), HealthScoreProvider)


def test_health_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_perfect_inputs_score_excellent():
    inputs = HealthInputs(
        savings_rate=0.25,
        essential_coverage_months=8,
        budget_adherence=1.0,
        debt_to_asset=0.0,
        income_stability=1.0,
    )
    result = WeightedHealthScorer().score(inputs)
    assert result.score == 100
    assert result.band == "excellent"
    assert len(result.components) == 5


def test_poor_inputs_score_needs_attention():
    inputs = HealthInputs(
        savings_rate=0.0,
        essential_coverage_months=0.0,
        budget_adherence=0.1,
        debt_to_asset=1.0,
        income_stability=0.2,
    )
    result = WeightedHealthScorer().score(inputs)
    assert result.score < 40
    assert result.band == "needs attention"


def test_health_components_are_transparent():
    result = WeightedHealthScorer().score(HealthInputs(0.10, 3, 0.8, 0.3, 0.7))
    # overall is the weighted mean of the component scores
    expected = round(sum(c.score * c.weight for c in result.components))
    assert result.score == expected
    for component in result.components:
        assert component.detail  # every component explains itself


# --------------------------------------------------------------- anomaly
def test_anomaly_detector_satisfies_protocol():
    assert isinstance(StatisticalAnomalyDetector(), AnomalyProvider)


def _obs(tid, payee, amount, day):
    return AmountObservation(
        transaction_id=tid,
        payee_normalized=payee,
        category_id=None,
        amount_minor=amount,
        occurred_at=datetime(2026, 7, day, tzinfo=UTC),
    )


def test_amount_spike_detected():
    # four normal ~2000 charges, then a 20000 spike
    obs = [_obs(f"t{i}", "corner store", -2000, i + 1) for i in range(4)]
    obs.append(_obs("spike", "corner store", -20000, 6))
    anomalies = StatisticalAnomalyDetector().detect(obs)
    spikes = [a for a in anomalies if a.kind == AnomalyKind.AMOUNT_SPIKE]
    assert spikes and spikes[0].transaction_id == "spike"
    assert spikes[0].explanation


def test_duplicate_charge_detected():
    obs = [
        _obs("a", "netflix", -1599, 1),
        _obs("b", "netflix", -1599, 2),  # same amount, 1 day later
    ]
    anomalies = StatisticalAnomalyDetector().detect(obs)
    dupes = [a for a in anomalies if a.kind == AnomalyKind.DUPLICATE]
    assert dupes and dupes[0].transaction_id == "b"


def test_large_new_payee_detected():
    anomalies = StatisticalAnomalyDetector().detect([_obs("big", "new lawyer llc", -250000, 1)])
    kinds = {a.kind for a in anomalies}
    assert AnomalyKind.NEW_PAYEE_LARGE in kinds


def test_normal_activity_no_anomalies():
    obs = [_obs(f"t{i}", "coffee", -450 - i, i + 1) for i in range(6)]
    anomalies = StatisticalAnomalyDetector().detect(obs)
    assert anomalies == []


# --------------------------------------------------------------- recommender
def test_recommender_satisfies_protocol():
    assert isinstance(HeuristicRecommender(), RecommendationProvider)


def test_rebalance_recommendation_maps_to_real_action():
    context = RecommendationContext(
        over_budget_lines=({"line_id": "dining", "name": "Dining out", "overage_minor": 6200},),
        underspent_lines=({"line_id": "groceries", "name": "Groceries", "remaining_minor": 16380},),
    )
    recs = HeuristicRecommender().recommend(context)
    rebalance = [r for r in recs if r.kind.value == "budget_rebalance"]
    assert rebalance
    action = rebalance[0].action
    assert action["action"] == "budget_rebalance"
    assert action["amount_minor"] == 6200
    assert action["from_line_id"] == "groceries"
    assert action["to_line_id"] == "dining"
    assert rebalance[0].severity == "attention"


def test_no_rebalance_when_no_donor_can_cover():
    context = RecommendationContext(
        over_budget_lines=({"line_id": "dining", "name": "Dining", "overage_minor": 6200},),
        underspent_lines=({"line_id": "g", "name": "Groceries", "remaining_minor": 1000},),
    )
    recs = HeuristicRecommender().recommend(context)
    assert not [r for r in recs if r.kind.value == "budget_rebalance"]


def test_positive_recommendation_has_no_action():
    context = RecommendationContext(savings_rate=0.22)
    recs = HeuristicRecommender().recommend(context)
    good = [r for r in recs if r.severity == "good"]
    assert good
    assert good[0].action == {}  # good news doesn't nag


# --------------------------------------------------------------- automation engine
def test_conditions_all_and_any():
    feats = {"payee_normalized": "netflix", "amount_minor": -1599}
    assert conditions_match(
        {"all": [{"field": "payee_normalized", "op": "contains", "value": "netflix"}]}, feats
    )
    assert not conditions_match(
        {
            "all": [
                {"field": "payee_normalized", "op": "contains", "value": "netflix"},
                {"field": "amount_minor", "op": "gte", "value": 0},
            ]
        },
        feats,
    )
    assert conditions_match(
        {
            "any": [
                {"field": "payee_normalized", "op": "contains", "value": "spotify"},
                {"field": "payee_normalized", "op": "contains", "value": "netflix"},
            ]
        },
        feats,
    )


def test_empty_conditions_never_match():
    assert not conditions_match({}, {"payee_normalized": "anything"})


def test_unknown_field_or_op_rejected():
    import pytest

    with pytest.raises(AutomationError):
        conditions_match({"all": [{"field": "secret", "op": "eq", "value": 1}]}, {})
    with pytest.raises(AutomationError):
        conditions_match({"all": [{"field": "memo", "op": "regex", "value": ".*"}]}, {"memo": "x"})


def test_action_allow_list_enforced():
    import pytest

    validate_actions([{"type": "set_category", "slug": "groceries"}])  # ok
    with pytest.raises(AutomationError):
        validate_actions([{"type": "post_journal_entry"}])  # not allowed


def test_stop_processing_halts_lower_priority():
    class FakeRule:
        def __init__(self, rid, name, priority, conditions, actions, stop):
            self.id = rid
            self.name = name
            self.priority = priority
            self.conditions = conditions
            self.actions = actions
            self.stop_processing = stop
            self.is_active = True

    rules = [
        FakeRule(
            "r1",
            "netflix",
            10,
            {"all": [{"field": "payee_normalized", "op": "contains", "value": "netflix"}]},
            [{"type": "add_tag", "name": "subscription"}],
            True,
        ),
        FakeRule(
            "r2",
            "catch-all",
            20,
            {"any": [{"field": "amount_minor", "op": "lte", "value": 0}]},
            [{"type": "flag_review"}],
            False,
        ),
    ]
    matches = evaluate_rules(rules, {"payee_normalized": "netflix", "amount_minor": -1599})
    assert len(matches) == 1
    assert matches[0].rule_id == "r1"


# =============================================================================
# Regression: HeuristicRecommender crashed on any real upcoming bill.
#
# context.upcoming_bills was "previously always empty" (see
# apps/finance/bills.py), so nothing ever exercised this branch of the
# recommender with real data — the DTO the selector built and the fields the
# recommender read had drifted apart silently. Fixed by testing through the
# real selector, not a hand-built context, which is the only way this class
# of mismatch gets caught before a bill is actually due in someone's account.
# =============================================================================
import uuid  # noqa: E402
from datetime import timedelta  # noqa: E402

from django.utils import timezone  # noqa: E402

from apps.finance import bills as bill_services  # noqa: E402
from apps.finance import services as finance_services  # noqa: E402
from apps.finance.models import CategoryKind  # noqa: E402
from apps.intelligence import selectors as intel_selectors  # noqa: E402
from tests.utils import tenant_scope  # noqa: E402

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


def test_a_real_upcoming_bill_does_not_crash_the_recommender(tenant):
    """The exact reported crash: KeyError: 'due_label' the moment a real bill
    reaches the recommender."""
    with tenant_scope(tenant):
        category = finance_services.create_category(
            name="Utilities", kind=CategoryKind.EXPENSE, currency="USD"
        )
        bill_services.create_bill(
            name="Electric bill",
            amount_minor=8_500,
            currency="USD",
            due_on=timezone.localdate() + timedelta(days=3),
            category=category,
        )

        context = intel_selectors.build_recommendation_context()
        assert context.upcoming_bills, "fixture bill should appear as upcoming"

        recommendations = HeuristicRecommender().recommend(context)
        bill_recs = [r for r in recommendations if r.kind == "bill_upcoming"]
        assert bill_recs, "expected a bill_upcoming recommendation"


def test_the_due_label_matches_the_real_number_of_days(tenant):
    with tenant_scope(tenant):
        category = finance_services.create_category(
            name="Utilities", kind=CategoryKind.EXPENSE, currency="USD"
        )
        bill_services.create_bill(
            name="Internet",
            amount_minor=6_000,
            currency="USD",
            due_on=timezone.localdate() + timedelta(days=1),
            category=category,
        )
        context = intel_selectors.build_recommendation_context()
        [rec] = [r for r in HeuristicRecommender().recommend(context) if r.kind == "bill_upcoming"]
        assert "tomorrow" in rec.title


def test_the_bill_action_is_one_the_frontend_can_actually_execute(tenant):
    """The provider's own stated rule: never propose an action the product
    can't back. `bill_id` is real; nothing here is fabricated."""
    with tenant_scope(tenant):
        category = finance_services.create_category(
            name="Utilities", kind=CategoryKind.EXPENSE, currency="USD"
        )
        bill = bill_services.create_bill(
            name="Water",
            amount_minor=4_000,
            currency="USD",
            due_on=timezone.localdate() + timedelta(days=5),
            category=category,
        )
        context = intel_selectors.build_recommendation_context()
        [rec] = [r for r in HeuristicRecommender().recommend(context) if r.kind == "bill_upcoming"]
        assert rec.action == {"action": "bill_upcoming", "bill_id": str(bill.id)}


def test_multiple_upcoming_bills_each_get_their_own_recommendation(tenant):
    with tenant_scope(tenant):
        category = finance_services.create_category(
            name="Utilities", kind=CategoryKind.EXPENSE, currency="USD"
        )
        for name, days in (("Electric", 2), ("Water", 5), ("Internet", 10)):
            bill_services.create_bill(
                name=name,
                amount_minor=5_000,
                currency="USD",
                due_on=timezone.localdate() + timedelta(days=days),
                category=category,
            )
        context = intel_selectors.build_recommendation_context()
        bill_recs = [r for r in HeuristicRecommender().recommend(context) if r.kind == "bill_upcoming"]
        assert len(bill_recs) == 3
