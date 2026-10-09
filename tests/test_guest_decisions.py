"""A decision with no account.

The guest try answers from figures the visitor typed. It must not open the
tenant catalogue, call the language model, or leave a row behind.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.projections.share_models import DecisionShare

pytestmark = pytest.mark.django_db

BASE = "/api/v1/projections"


def _position(**over):
    body = {
        "currency": "KES",
        "monthly_net_income_minor": 200_000_00,
        "monthly_expenses_minor": 80_000_00,
        "liquid_minor": 500_000_00,
    }
    body.update(over)
    return body


def test_guest_catalogue_lists_sacco_without_a_session():
    response = APIClient().get(f"{BASE}/guest/questions/")
    assert response.status_code == 200
    slugs = {row["slug"] for row in response.json()["results"]}
    assert "sacco-loan" in slugs


def test_tenant_catalogue_stays_closed():
    assert APIClient().get(f"{BASE}/questions/").status_code in (401, 403)


def test_guest_sacco_answer_is_stated_and_not_stored():
    before = DecisionShare.objects.count()
    response = APIClient().post(
        f"{BASE}/guest/questions/sacco-loan/",
        {
            "position": _position(),
            "inputs": {"amount_minor": 100_000_00, "shares_held_minor": 80_000_00},
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["source"] == "stated"
    assert body["explanation"]["llm_used"] is False
    assert any("stated for this try" in line for line in body["assumptions"])
    prose = " ".join(body["explanation"]["paragraphs"])
    assert "typed for this try" in prose
    assert "ledger already records" not in prose
    assert body["verdict"]
    assert DecisionShare.objects.count() == before


def test_guest_rejects_an_unknown_currency():
    response = APIClient().post(
        f"{BASE}/guest/questions/sacco-loan/",
        {"position": _position(currency="ZZZ"), "inputs": {"amount_minor": 1}},
        format="json",
    )
    assert response.status_code == 400


def test_guest_unknown_question_lists_what_exists():
    response = APIClient().post(
        f"{BASE}/guest/questions/not-a-question/",
        {"position": _position(), "inputs": {}},
        format="json",
    )
    assert response.status_code == 404
    assert "sacco-loan" in response.json()["available"]
