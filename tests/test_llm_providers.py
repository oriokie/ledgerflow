"""LLM configuration and the LLM-backed coach providers.

The properties pinned hardest are the ones that decide whether this is safe to
switch on in a financial product:

  * the deterministic provider is always the floor, never replaced;
  * every failure mode falls back rather than breaking;
  * model output is validated, and anything unsupported is dropped;
  * financial context is not sent to a third party without explicit consent.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from apps.intelligence import llm
from apps.intelligence.models import InsightKind, InsightSeverity
from apps.intelligence.protocols import CoachContext
from apps.intelligence.providers.llm_coach import LLMCoach, LLMNarrator
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


def _overspending_ctx() -> CoachContext:
    return _ctx(
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


def _returning(value):
    """A stand-in `complete` that ignores its kwargs and returns `value`."""

    def _stub(**_kwargs):
        return value

    return _stub


def _enable(settings, **overrides):
    """Turn the LLM on with a hosted provider and consent granted."""
    settings.LLM_ENABLED = True
    settings.LLM_PROVIDER = "groq"
    settings.LLM_MODEL = "llama-3.3-70b-versatile"
    settings.LLM_BASE_URL = ""
    settings.LLM_API_KEY = "test-key"
    settings.LLM_SHARE_FINANCIAL_CONTEXT = True
    for key, value in overrides.items():
        setattr(settings, key, value)


# ------------------------------------------------------------------- presets
def test_presets_cover_popular_free_and_local_options():
    ids = set(llm.PROVIDER_PRESETS)
    # Free tiers, paid hosted, and local — a user with no budget can still use
    # the feature.
    assert {"groq", "google", "openrouter", "together", "mistral"} <= ids
    assert {"openai", "anthropic", "deepseek"} <= ids
    assert {"ollama", "lmstudio"} <= ids
    # `custom` is the escape hatch that stops an unlisted endpoint needing code.
    assert "custom" in ids


def test_local_presets_need_no_api_key():
    for key in ("ollama", "lmstudio"):
        assert llm.PROVIDER_PRESETS[key].requires_key is False


def test_most_providers_share_the_openai_wire_format():
    """The reason this is one small adapter rather than a dozen SDKs."""
    wires = [p.wire for p in llm.PROVIDER_PRESETS.values()]
    assert wires.count("openai") >= 7
    assert set(wires) == {"openai", "anthropic", "google"}


def test_preset_supplies_defaults_and_settings_override_them(settings):
    _enable(settings)
    config = llm.get_llm_config()
    assert config.base_url == llm.PROVIDER_PRESETS["groq"].base_url

    settings.LLM_BASE_URL = "https://my-proxy.internal/v1"
    settings.LLM_MODEL = "my-model"
    overridden = llm.get_llm_config()
    assert overridden.base_url == "https://my-proxy.internal/v1"
    assert overridden.model == "my-model"


# ------------------------------------------------------------- availability
def test_disabled_by_default(settings):
    settings.LLM_ENABLED = False
    available, reason = llm.llm_available()
    assert available is False
    assert "turned off" in reason


def test_missing_api_key_is_explained_not_silent(settings):
    _enable(settings, LLM_API_KEY="")
    available, reason = llm.llm_available()
    assert available is False
    # The common failure is silent: switch it on, nothing happens, nothing to
    # look at. The reason string exists for that.
    assert "API key" in reason


def test_external_providers_require_explicit_data_sharing_consent(settings):
    """Sending a household's spending to a third party is a deliberate choice."""
    _enable(settings, LLM_SHARE_FINANCIAL_CONTEXT=False)
    available, reason = llm.llm_available()
    assert available is False
    assert "financial context" in reason


def test_local_providers_are_exempt_from_the_sharing_gate(settings):
    # Nothing leaves the machine, so there is nothing to consent to.
    settings.LLM_ENABLED = True
    settings.LLM_PROVIDER = "ollama"
    settings.LLM_MODEL = "llama3.2"
    settings.LLM_BASE_URL = ""
    settings.LLM_API_KEY = ""
    settings.LLM_SHARE_FINANCIAL_CONTEXT = False

    available, reason = llm.llm_available()
    assert available is True, reason
    assert llm.get_llm_config().is_local is True


# --------------------------------------------------------------- JSON parsing
def test_json_is_extracted_from_a_markdown_fence(monkeypatch):
    """Models wrap JSON in fences despite being told not to. Refusing that
    would make the feature flaky for no benefit."""
    monkeypatch.setattr(llm, "complete", lambda **_: '```json\n[{"a": 1}]\n```')
    assert llm.complete_json(system="s", user="u") == [{"a": 1}]


def test_json_is_extracted_from_surrounding_prose(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda **_: 'Sure! Here you go: [{"a": 1}] Hope that helps.')
    assert llm.complete_json(system="s", user="u") == [{"a": 1}]


def test_unparseable_output_raises_rather_than_guessing(monkeypatch):
    for body in ("", "no json at all", "[{unterminated"):
        monkeypatch.setattr(llm, "complete", _returning(body))
        with pytest.raises(llm.LLMError):
            llm.complete_json(system="s", user="u")


# ------------------------------------------------------------------ fallback
def test_rule_based_insights_survive_when_the_llm_is_off(settings):
    settings.LLM_ENABLED = False
    produced = LLMCoach().generate(_overspending_ctx())
    # The deterministic provider is the floor, not a stub.
    assert any(i.kind == InsightKind.OVERSPENDING for i in produced)


def test_a_failing_llm_never_costs_the_user_their_insights(settings, monkeypatch):
    _enable(settings)
    monkeypatch.setattr(
        "apps.intelligence.providers.llm_coach.complete_json",
        lambda **_: (_ for _ in ()).throw(llm.LLMError("boom")),
    )
    produced = LLMCoach().generate(_overspending_ctx())
    # A misconfigured key must not mean an empty screen.
    assert any(i.kind == InsightKind.OVERSPENDING for i in produced)


def test_llm_candidates_are_added_to_the_baseline_not_swapped_in(settings, monkeypatch):
    _enable(settings)
    monkeypatch.setattr(
        "apps.intelligence.providers.llm_coach.complete_json",
        lambda **_: [
            {
                "kind": "savings_opportunity",
                "severity": "opportunity",
                "title": "Model-written insight",
                "body": "Something the rules didn't spot.",
                "rationale": "Derived from the supplied figures.",
            }
        ],
    )
    produced = LLMCoach().generate(_overspending_ctx())
    kinds = {i.kind for i in produced}
    # A predicted overdraft must never be missed because a model had an off day.
    assert InsightKind.OVERSPENDING in kinds
    assert InsightKind.SAVINGS_OPPORTUNITY in kinds


# ---------------------------------------------------------------- validation
def test_malformed_candidates_are_dropped(settings, monkeypatch):
    _enable(settings)
    monkeypatch.setattr(
        "apps.intelligence.providers.llm_coach.complete_json",
        lambda **_: [
            {"kind": "not_a_real_kind", "severity": "info", "title": "x", "body": "y", "rationale": "z"},
            {"kind": "savings_opportunity", "severity": "apocalyptic", "title": "x", "body": "y", "rationale": "z"},
            # No rationale — the contract that stops unsupported claims.
            {"kind": "savings_opportunity", "severity": "info", "title": "x", "body": "y"},
            "not even an object",
        ],
    )
    produced = LLMCoach().generate(_ctx())
    assert produced == [], "every malformed candidate should have been dropped"


def test_a_model_cannot_supply_its_own_evidence(settings, monkeypatch):
    """The model phrases figures; it does not produce them. A number a model
    invented is a number nobody computed."""
    _enable(settings)
    monkeypatch.setattr(
        "apps.intelligence.providers.llm_coach.complete_json",
        lambda **_: [
            {
                "kind": "savings_opportunity",
                "severity": "opportunity",
                "title": "Made-up figures",
                "body": "You could save 999.",
                "rationale": "Because.",
                "evidence": {"over_minor": 99_999_99},
            }
        ],
    )
    [candidate] = [i for i in LLMCoach().generate(_ctx()) if i.provenance.kind == "llm"]
    assert candidate.evidence == {}


def test_llm_candidates_are_confidence_discounted(settings, monkeypatch):
    _enable(settings)
    monkeypatch.setattr(
        "apps.intelligence.providers.llm_coach.complete_json",
        lambda **_: [
            {
                "kind": "savings_opportunity",
                "severity": "opportunity",
                "title": "A suggestion",
                "body": "Body.",
                "rationale": "Reason.",
            }
        ],
    )
    [candidate] = [i for i in LLMCoach().generate(_ctx()) if i.provenance.kind == "llm"]
    # Described, not derived — it ranks below a rule-based equivalent.
    assert candidate.confidence < 1.0


def test_the_model_cannot_flood_the_feed(settings, monkeypatch):
    _enable(settings)
    monkeypatch.setattr(
        "apps.intelligence.providers.llm_coach.complete_json",
        lambda **_: [
            {
                "kind": "savings_opportunity",
                "severity": "info",
                "title": f"Insight {n}",
                "body": "Body.",
                "rationale": "Reason.",
            }
            for n in range(50)
        ],
    )
    produced = [i for i in LLMCoach().generate(_ctx()) if i.provenance.kind == "llm"]
    assert len(produced) <= 6


# ----------------------------------------------------------------- narration
def test_narrator_falls_back_to_the_template_on_failure(settings, monkeypatch):
    _enable(settings)
    monkeypatch.setattr(
        "apps.intelligence.providers.llm_coach.complete_json",
        lambda **_: (_ for _ in ()).throw(llm.LLMError("timeout")),
    )
    draft = LLMNarrator().write_briefing(period="daily", context=_ctx(), insights=[])
    assert draft.headline, "a failed narration must still produce a briefing"


def test_narrator_keeps_engine_metrics_when_the_model_rewrites_prose(settings, monkeypatch):
    _enable(settings)
    monkeypatch.setattr(
        "apps.intelligence.providers.llm_coach.complete_json",
        lambda **_: {"headline": "A calmer headline", "summary": "Two sentences of prose."},
    )
    draft = LLMNarrator().write_briefing(period="daily", context=_ctx(savings_rate=0.2), insights=[])

    assert draft.headline == "A calmer headline"
    # The model rewrote the words; it did not recount anything.
    assert draft.metrics["savings_rate"] == 0.2
    assert draft.provenance.kind == "llm"


def test_narrator_rejects_a_partial_response(settings, monkeypatch):
    _enable(settings)
    monkeypatch.setattr(
        "apps.intelligence.providers.llm_coach.complete_json",
        lambda **_: {"headline": "Only a headline"},
    )
    draft = LLMNarrator().write_briefing(period="daily", context=_ctx(), insights=[])
    # Falls back rather than shipping a briefing with no body.
    assert draft.provenance.kind == "rule"


# ------------------------------------------------------------------ endpoint
def test_settings_endpoint_reports_configuration_without_the_key(tenant_context, settings):
    _enable(settings)
    _, client = tenant_context
    resp = client.get("/api/v1/intelligence/llm-settings/")

    assert resp.status_code == 200, resp.data
    assert resp.data["enabled"] is True
    assert resp.data["provider"] == "groq"
    assert resp.data["api_key_present"] is True
    # The credential itself must never cross this boundary.
    assert "api_key" not in resp.data
    assert "test-key" not in str(resp.data)


def test_settings_endpoint_lists_presets_for_the_ui(tenant_context):
    _, client = tenant_context
    presets = client.get("/api/v1/intelligence/llm-settings/").data["presets"]
    ids = {p["id"] for p in presets}
    assert {"groq", "ollama", "openai", "custom"} <= ids
    assert any(p["free_tier"] for p in presets)
    assert any(p["is_local"] for p in presets)


def test_settings_endpoint_explains_why_it_is_unavailable(tenant_context, settings):
    settings.LLM_ENABLED = False
    _, client = tenant_context
    data = client.get("/api/v1/intelligence/llm-settings/").data
    assert data["available"] is False
    assert data["reason"]


def test_active_providers_are_reported(tenant_context, settings):
    settings.INTELLIGENCE_PROVIDERS = {
        "insight": "apps.intelligence.providers.llm_coach.LLMCoach",
    }
    _, client = tenant_context
    data = client.get("/api/v1/intelligence/llm-settings/").data
    assert data["insight_provider"].endswith("LLMCoach")
    # Unset capabilities report the deterministic default rather than blank.
    assert data["narrative_provider"].endswith("TemplateNarrator")


# ---------------------------------------------------------------- scheduling
def test_scheduled_coach_run_is_idempotent(tenant):
    """The nightly sweep must refresh, not accumulate — the same property that
    makes insight dedupe work."""
    from apps.intelligence.models import Insight
    from apps.intelligence.tasks import run_coach_for_tenant

    # The task binds its own tenant; the assertions need their own scope.
    run_coach_for_tenant(str(tenant))
    with tenant_scope(tenant):
        first = Insight.objects.count()

    run_coach_for_tenant(str(tenant))
    with tenant_scope(tenant):
        assert Insight.objects.count() == first


def test_scheduled_run_produces_a_daily_briefing(tenant):
    from apps.intelligence.models import Briefing, BriefingPeriod
    from apps.intelligence.tasks import run_coach_for_tenant

    run_coach_for_tenant(str(tenant))
    with tenant_scope(tenant):
        assert Briefing.objects.filter(period=BriefingPeriod.DAILY).exists()
