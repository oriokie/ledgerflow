"""Provider registry — the one place that maps a capability to its
implementation.

Callers never instantiate a provider directly; they ask the registry:

    categorizer = get_categorizer()
    suggestion = categorizer.suggest_category(features)

Which concrete class comes back is decided by settings, so switching
categorization from rules to an LLM (or an ensemble of both) is a
config change and a deploy — no caller touches its import. Defaults are the
deterministic providers, so the product is fully functional with zero AI
configuration, and any future LLM provider inherits these as its offline
fallback.

    INTELLIGENCE_PROVIDERS = {
        "categorization": "apps.intelligence.providers.rules.RuleBasedCategorizer",
        "forecast":       "apps.intelligence.providers.statistical.MovingAverageForecaster",
        ...
    }
"""

from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string

from .protocols import (
    AnomalyProvider,
    CategorizationProvider,
    ForecastProvider,
    HealthScoreProvider,
    InsightProvider,
    NarrativeProvider,
    RecommendationProvider,
)

_DEFAULTS = {
    "categorization": "apps.intelligence.providers.rules.RuleBasedCategorizer",
    "forecast": "apps.intelligence.providers.statistical.MovingAverageForecaster",
    "health": "apps.intelligence.providers.health.WeightedHealthScorer",
    "anomaly": "apps.intelligence.providers.statistical.StatisticalAnomalyDetector",
    "recommendation": "apps.intelligence.providers.recommend.HeuristicRecommender",
    "insight": "apps.intelligence.providers.coach.RuleBasedCoach",
    "narrative": "apps.intelligence.providers.coach.TemplateNarrator",
}


def _resolve(capability: str):
    configured = getattr(settings, "INTELLIGENCE_PROVIDERS", {}) or {}
    dotted_path = configured.get(capability, _DEFAULTS[capability])
    return import_string(dotted_path)()


def get_categorizer() -> CategorizationProvider:
    return _resolve("categorization")


def get_forecaster() -> ForecastProvider:
    return _resolve("forecast")


def get_health_scorer() -> HealthScoreProvider:
    return _resolve("health")


def get_anomaly_detector() -> AnomalyProvider:
    return _resolve("anomaly")


def get_recommender() -> RecommendationProvider:
    return _resolve("recommendation")


def get_insight_provider() -> InsightProvider:
    return _resolve("insight")


def get_narrative_provider() -> NarrativeProvider:
    return _resolve("narrative")
