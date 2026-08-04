"""HTTP contract for the digital twin.

The `/ask/` endpoint is what these mostly defend, and the property that matters
is that it adds a way to *reach* the Phase 2 answers rather than a second
source of them: an answer arriving through a sentence must be the same answer
the form gives, computed by the same code, with the same assumptions attached.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

BASE = "/api/v1/twin"


def _account(client, opening=5_000_000):
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
# the twin
# ---------------------------------------------------------------------------


def test_the_twin_reports_its_parameters_and_the_evidence_behind_them(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.get(f"{BASE}/")
    assert res.status_code == 200
    assert res.data["confidence"] in ("none", "weak", "moderate", "strong")
    assert res.data["parameters"]
    for parameter in res.data["parameters"]:
        assert parameter["label"]
        assert parameter["detail"]
        assert "months_observed" in parameter
        assert "effective" in parameter


def test_a_workspace_with_no_history_says_it_knows_nothing(tenant_context):
    _, client = tenant_context
    res = client.get(f"{BASE}/")
    assert res.status_code == 200
    assert res.data["months_observed"] == 0
    assert res.data["confidence"] == "none"


# ---------------------------------------------------------------------------
# calibration
# ---------------------------------------------------------------------------


def test_calibration_with_nothing_scored_says_so(tenant_context):
    _, client = tenant_context
    res = client.get(f"{BASE}/calibration/")
    assert res.status_code == 200
    assert res.data["total_scored"] == 0
    assert "Not enough history" in res.data["headline"]
    assert res.data["notes"]


def test_recording_a_forecast_scores_and_predicts_in_one_call(tenant_context):
    """A product that records forecasts but never scores them accumulates the
    appearance of rigour."""
    _, client = tenant_context
    _account(client)
    res = client.post(f"{BASE}/calibration/", {}, format="json")
    assert res.status_code == 200
    assert "scored" in res.data
    assert "recorded" in res.data


def test_every_calibration_kind_is_reported_even_when_empty(tenant_context):
    _, client = tenant_context
    res = client.get(f"{BASE}/calibration/")
    kinds = {k["kind"] for k in res.data["kinds"]}
    assert kinds == {"monthly_spend", "monthly_income", "closing_liquid"}
    for kind in res.data["kinds"]:
        assert kind["detail"]


# ---------------------------------------------------------------------------
# asking in words
# ---------------------------------------------------------------------------


def test_a_question_reaches_the_same_evaluator_the_form_uses(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.post(
        f"{BASE}/ask/",
        {"question": "Can I afford this house at 3,000,000 with a 600,000 deposit at 9%?"},
        format="json",
    )
    assert res.status_code == 200, res.data
    assert res.data["answered"] is True
    assert res.data["matched"] == "afford-mortgage"
    assert res.data["verdict"]
    assert res.data["explanation"]["paragraphs"]
    assert res.data["assumptions"]


def test_the_answer_says_which_question_it_understood(tenant_context):
    """The user has to be able to see that the right thing was computed."""
    _, client = tenant_context
    _account(client)
    res = client.post(
        f"{BASE}/ask/",
        {"question": "Should I buy or rent? 3,000,000 at 9%, rent 120,000"},
        format="json",
    )
    assert res.data["understood_as"] == "Should I buy or rent?"


def test_a_question_it_cannot_compute_is_refused_with_what_it_can(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.post(f"{BASE}/ask/", {"question": "What is the meaning of life?"}, format="json")
    assert res.status_code == 200
    assert res.data["answered"] is False
    assert res.data["matched"] is None
    assert "Can I afford this mortgage?" in res.data["available"].values()


def test_a_question_missing_a_figure_names_it_rather_than_inventing_one(tenant_context):
    """A mortgage answered with an invented interest rate looks like an answer
    and is not one."""
    _, client = tenant_context
    _account(client)
    res = client.post(f"{BASE}/ask/", {"question": "Can I afford this mortgage?"}, format="json")
    assert res.data["answered"] is False
    assert res.data["matched"] == "afford-mortgage"
    assert "annual_rate" in res.data["missing"]
    assert "nothing is assumed" in res.data["detail"].lower()


def test_asking_on_an_empty_workspace_is_a_409(tenant_context):
    _, client = tenant_context
    res = client.post(
        f"{BASE}/ask/",
        {"question": "How much house can I comfortably afford at 9%?"},
        format="json",
    )
    assert res.status_code == 409


def test_no_model_configured_still_answers(tenant_context):
    """The default configuration, and it has to work."""
    _, client = tenant_context
    _account(client)
    res = client.post(
        f"{BASE}/ask/",
        {"question": "How much house can I comfortably afford at 9%?", "use_llm": False},
        format="json",
    )
    assert res.data["answered"] is True
    assert res.data["llm_used"] is False


def test_an_empty_question_is_rejected(tenant_context):
    _, client = tenant_context
    res = client.post(f"{BASE}/ask/", {"question": ""}, format="json")
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# auth and isolation
# ---------------------------------------------------------------------------


def test_the_twin_requires_authentication():
    from rest_framework.test import APIClient

    assert APIClient().get(f"{BASE}/").status_code in (401, 403)


def test_one_tenants_forecasts_are_invisible_to_another(tenant_context):
    from tests.conftest import _bearer_client
    from tests.factories import MembershipFactory

    _, client = tenant_context
    _account(client)
    client.post(f"{BASE}/calibration/", {}, format="json")

    other = MembershipFactory()
    other_client = _bearer_client(other.user, tenant_id=other.tenant_id)
    assert other_client.get(f"{BASE}/calibration/").data["total_scored"] == 0


def test_ask_and_the_form_agree_even_under_custom_assumptions(tenant_context):
    """The regression that motivated the shared dispatcher: /twin/ask/ used to
    call the evaluator without the workspace's assumption set, so a workspace
    that had customised its inflation view got one answer from the form and a
    different one from the same question asked in words. "Understood as" was
    true and the figures still differed."""
    _, client = tenant_context
    _account(client)
    # Make the workspace's assumptions deliberately unusual.
    client.patch("/api/v1/projections/assumptions/", {"annual_inflation": "0.1500"}, format="json")

    form = client.post(
        "/api/v1/projections/questions/afford-mortgage/",
        {"property_price_minor": 3_000_000, "deposit_minor": 600_000, "annual_rate": 0.09, "explain": False},
        format="json",
    ).data
    asked = client.post(
        f"{BASE}/ask/",
        {"question": "Can I afford this house at 30,000 with a 6,000 deposit at 9%?", "use_llm": False},
        format="json",
    ).data

    assert asked["answered"] is True
    assert asked["verdict"] == form["verdict"]
    form_figures = {f["label"]: f["amount_minor"] for f in form["because"]}
    asked_figures = {f["label"]: f["amount_minor"] for f in asked["because"]}
    assert form_figures == asked_figures
