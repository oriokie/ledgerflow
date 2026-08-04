"""HTTP contract for the Phase 2 decision-support endpoints.

The service layer is tested directly elsewhere. What these add is the wire
contract and the two properties only visible over HTTP: that a workspace with
nothing in it gets a usable error rather than a stack trace, and that every
answer arrives with its assumptions and a confidence attached — the product's
stated standard for decision support, enforced at the boundary rather than
remembered at each call site.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

BASE = "/api/v1/projections"


def _account(client, opening=8_000_000):
    return client.post(
        "/api/v1/finance/accounts/",
        {
            "name": "Checking",
            "account_type": "checking",
            "currency": "USD",
            "opening_balance_minor": opening,
        },
        format="json",
    ).data


# ---------------------------------------------------------------------------
# simulation
# ---------------------------------------------------------------------------


def test_simulation_returns_a_band_a_probability_and_its_seed(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.post(f"{BASE}/simulate/", {"months": 60, "trials": 40, "seed": 5}, format="json")
    assert res.status_code == 200
    assert res.data["seed"] == 5
    assert res.data["trials"] == 40
    assert 0 <= res.data["success_probability"] <= 1
    p = res.data["closing_net_worth"]
    assert p["p10"] <= p["p50"] <= p["p90"]
    assert res.data["bands"]
    assert res.data["assumptions"]


def test_the_same_seed_gives_the_same_answer_over_http(tenant_context):
    _, client = tenant_context
    _account(client)
    body = {"months": 60, "trials": 30, "seed": 42}
    first = client.post(f"{BASE}/simulate/", body, format="json").data
    second = client.post(f"{BASE}/simulate/", body, format="json").data
    assert first["closing_net_worth"] == second["closing_net_worth"]


def test_the_deterministic_line_travels_with_the_band(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.post(f"{BASE}/simulate/", {"months": 24, "trials": 20}, format="json")
    assert res.data["deterministic"] is not None
    assert len(res.data["deterministic"]["points"]) == 24


def test_the_trial_count_is_capped(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.post(f"{BASE}/simulate/", {"trials": 99_999}, format="json")
    assert res.status_code == 400


def test_simulating_an_unknown_scenario_is_a_404(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.post(
        f"{BASE}/simulate/",
        {"trials": 10, "scenario_id": "00000000-0000-0000-0000-000000000000"},
        format="json",
    )
    assert res.status_code == 404


def test_simulating_an_empty_workspace_is_a_409_with_an_instruction(tenant_context):
    _, client = tenant_context
    res = client.post(f"{BASE}/simulate/", {"trials": 10}, format="json")
    assert res.status_code == 409
    assert "Add a current" in res.data["detail"]


# ---------------------------------------------------------------------------
# sensitivity and what-if
# ---------------------------------------------------------------------------


def test_sensitivity_ranks_the_levers(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.get(f"{BASE}/sensitivity/?months=120")
    assert res.status_code == 200
    spreads = [s["spread_minor"] for s in res.data["swings"]]
    assert spreads == sorted(spreads, reverse=True)
    assert res.data["notes"]


def test_each_swing_says_which_direction_helps(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.get(f"{BASE}/sensitivity/")
    for swing in res.data["swings"]:
        assert swing["direction"] in ("higher is better", "higher is worse")


def test_a_what_if_reports_both_legs_and_the_delta(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.post(f"{BASE}/what-if/", {"months": 120, "inflation": 0.10}, format="json")
    assert res.status_code == 200
    assert "baseline_closing_minor" in res.data
    assert "changed_closing_minor" in res.data
    assert "delta_minor" in res.data
    assert res.data["notes"]


def test_a_what_if_that_changes_nothing_is_a_400(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.post(f"{BASE}/what-if/", {"months": 120}, format="json")
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# risk
# ---------------------------------------------------------------------------


def test_risk_reports_factors_weakest_first_with_a_headline(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.get(f"{BASE}/risk/")
    assert res.status_code == 200
    assert res.data["headline"]
    scores = [f["score"] for f in res.data["factors"]]
    assert scores == sorted(scores)
    assert res.data["resilience"] == (scores[0] if scores else 0)


def test_risk_on_an_empty_workspace_is_a_409(tenant_context):
    _, client = tenant_context
    res = client.get(f"{BASE}/risk/")
    assert res.status_code == 409


# ---------------------------------------------------------------------------
# the decision assistant
# ---------------------------------------------------------------------------


def test_the_catalogue_lists_every_question_and_what_it_needs(tenant_context):
    _, client = tenant_context
    res = client.get(f"{BASE}/questions/")
    assert res.status_code == 200
    slugs = {q["slug"] for q in res.data["results"]}
    assert slugs == {
        "afford-mortgage",
        "how-much-house",
        "debt-or-invest",
        "retire",
        "buy-or-rent",
    }
    for question in res.data["results"]:
        assert question["question"]
        assert question["fields"]
        assert "explain" not in {f["name"] for f in question["fields"]}


@pytest.mark.parametrize(
    "slug,payload",
    [
        (
            "afford-mortgage",
            {"property_price_minor": 20_000_000, "deposit_minor": 5_000_000, "annual_rate": 0.09},
        ),
        ("how-much-house", {"annual_rate": 0.09}),
        ("debt-or-invest", {"monthly_amount_minor": 50_000, "expected_return": 0.07}),
        ("retire", {"years_until": 20, "monthly_income_needed_minor": 300_000}),
        (
            "buy-or-rent",
            {
                "property_price_minor": 20_000_000,
                "deposit_minor": 5_000_000,
                "annual_rate": 0.09,
                "monthly_rent_minor": 120_000,
            },
        ),
    ],
)
def test_every_question_answers_with_a_verdict_and_its_assumptions(tenant_context, slug, payload):
    """The boundary contract: nothing returns a bare number."""
    _, client = tenant_context
    _account(client)
    res = client.post(f"{BASE}/questions/{slug}/", payload, format="json")
    assert res.status_code == 200, res.data
    assert res.data["verdict"]
    assert res.data["headline"]
    assert res.data["confidence"] in ("measured", "mixed", "assumed")
    assert res.data["explanation"]["paragraphs"]
    if res.data["verdict"] != "unknown":
        assert res.data["assumptions"]


def test_an_unknown_question_lists_the_ones_that_exist(tenant_context):
    _, client = tenant_context
    res = client.post(f"{BASE}/questions/should-i-buy-a-boat/", {}, format="json")
    assert res.status_code == 404
    assert "afford-mortgage" in res.data["available"]


def test_findings_and_prose_are_separate_so_a_number_has_two_homes(tenant_context):
    """A client that wants its own layout gets structured findings, and the
    explanation never becomes the only place a figure appears."""
    _, client = tenant_context
    _account(client)
    res = client.post(
        f"{BASE}/questions/afford-mortgage/",
        {"property_price_minor": 20_000_000, "deposit_minor": 5_000_000, "annual_rate": 0.09},
        format="json",
    )
    assert res.data["because"]
    assert any(f["amount_minor"] for f in res.data["because"])
    assert res.data["explanation"]["paragraphs"]


def test_no_model_configured_is_not_an_error(tenant_context):
    """The product ships fully functional with LLM features off, which is the
    default."""
    _, client = tenant_context
    _account(client)
    res = client.post(f"{BASE}/questions/how-much-house/", {"annual_rate": 0.09}, format="json")
    assert res.status_code == 200
    assert res.data["explanation"]["llm_used"] is False
    assert res.data["explanation"]["rejected_reason"] == ""


def test_a_bad_rate_is_a_400_with_the_reason(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.post(
        f"{BASE}/questions/afford-mortgage/",
        {"property_price_minor": 20_000_000, "deposit_minor": 5_000_000, "annual_rate": 9.0},
        format="json",
    )
    assert res.status_code == 400
    assert "fractions" in res.data["detail"]


def test_asking_on_an_empty_workspace_is_a_409(tenant_context):
    _, client = tenant_context
    res = client.post(f"{BASE}/questions/how-much-house/", {"annual_rate": 0.09}, format="json")
    assert res.status_code == 409


def test_the_decision_endpoints_require_authentication():
    from rest_framework.test import APIClient

    assert APIClient().get(f"{BASE}/questions/").status_code in (401, 403)
