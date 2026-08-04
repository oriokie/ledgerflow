"""HTTP contract for the Phase 1 projection API.

The service layer is tested directly elsewhere; what these add is the wire
contract — status codes, payload shape, error handling, and the two things
that are only visible over HTTP: that an empty workspace gets a usable error
rather than a stack trace, and that one tenant's scenarios are invisible to
another through the API as well as through the ORM.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db

BASE = "/api/v1/projections"


def _account(client, opening=1_000_000):
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


def _scenario(client, name="Buy a house", **extra):
    payload = {"name": name, "horizon_months": 120}
    payload.update(extra)
    return client.post(f"{BASE}/scenarios/", payload, format="json")


# ---------------------------------------------------------------------------
# scenarios
# ---------------------------------------------------------------------------


def test_create_and_list_a_scenario(tenant_context):
    _, client = tenant_context
    created = _scenario(client)
    assert created.status_code == 201
    assert created.data["name"] == "Buy a house"
    assert created.data["visibility"] == "private"

    listed = client.get(f"{BASE}/scenarios/")
    assert listed.status_code == 200
    assert len(listed.data["results"]) == 1


def test_scenarios_can_be_filtered_by_status(tenant_context):
    _, client = tenant_context
    _scenario(client, name="Draft one")
    active = _scenario(client, name="Active one", status="active").data
    assert active["status"] == "active"

    res = client.get(f"{BASE}/scenarios/?status=active")
    assert [s["name"] for s in res.data["results"]] == ["Active one"]


def test_add_an_event_and_read_it_back(tenant_context):
    _, client = tenant_context
    scenario = _scenario(client).data
    res = client.post(
        f"{BASE}/scenarios/{scenario['id']}/events/",
        {
            "kind": "home_purchase",
            "start_month": 12,
            "params": {"price_minor": 10_000_000, "deposit_minor": 2_000_000},
        },
        format="json",
    )
    assert res.status_code == 201
    assert res.data["kind"] == "home_purchase"

    detail = client.get(f"{BASE}/scenarios/{scenario['id']}/")
    assert len(detail.data["events"]) == 1


def test_an_event_with_bad_parameters_is_a_400_not_a_500(tenant_context):
    _, client = tenant_context
    scenario = _scenario(client).data
    res = client.post(
        f"{BASE}/scenarios/{scenario['id']}/events/",
        {"kind": "home_purchase", "params": {"prix_minor": 1}},
        format="json",
    )
    assert res.status_code == 400


def test_an_unknown_event_kind_is_rejected(tenant_context):
    _, client = tenant_context
    scenario = _scenario(client).data
    res = client.post(
        f"{BASE}/scenarios/{scenario['id']}/events/",
        {"kind": "winning_the_lottery", "params": {}},
        format="json",
    )
    assert res.status_code == 400


def test_an_event_beyond_the_horizon_is_rejected(tenant_context):
    _, client = tenant_context
    scenario = _scenario(client, horizon_months=12).data
    res = client.post(
        f"{BASE}/scenarios/{scenario['id']}/events/",
        {"kind": "invest_more", "start_month": 60, "params": {"monthly_amount_minor": 100}},
        format="json",
    )
    assert res.status_code == 400
    assert "outside" in res.data["detail"]


def test_update_and_delete_an_event(tenant_context):
    _, client = tenant_context
    scenario = _scenario(client).data
    event = client.post(
        f"{BASE}/scenarios/{scenario['id']}/events/",
        {"kind": "invest_more", "params": {"monthly_amount_minor": 1_000}},
        format="json",
    ).data

    patched = client.patch(
        f"{BASE}/scenarios/{scenario['id']}/events/{event['id']}/",
        {"is_enabled": False},
        format="json",
    )
    assert patched.status_code == 200
    assert patched.data["is_enabled"] is False

    deleted = client.delete(f"{BASE}/scenarios/{scenario['id']}/events/{event['id']}/")
    assert deleted.status_code == 204
    assert client.get(f"{BASE}/scenarios/{scenario['id']}/").data["events"] == []


def test_patch_a_scenario(tenant_context):
    _, client = tenant_context
    scenario = _scenario(client).data
    res = client.patch(
        f"{BASE}/scenarios/{scenario['id']}/",
        {"description": "Two-bed near the school", "visibility": "household"},
        format="json",
    )
    assert res.status_code == 200
    assert res.data["visibility"] == "household"


def test_duplicate_and_archive(tenant_context):
    _, client = tenant_context
    scenario = _scenario(client, status="active").data

    copy = client.post(f"{BASE}/scenarios/{scenario['id']}/duplicate/", {}, format="json")
    assert copy.status_code == 201
    assert copy.data["status"] == "draft"
    assert copy.data["duplicated_from_id"] == scenario["id"]

    archived = client.post(f"{BASE}/scenarios/{scenario['id']}/archive/", {}, format="json")
    assert archived.data["status"] == "archived"


def test_deleting_a_scenario_removes_it_from_the_list(tenant_context):
    _, client = tenant_context
    scenario = _scenario(client).data
    assert client.delete(f"{BASE}/scenarios/{scenario['id']}/").status_code == 204
    assert client.get(f"{BASE}/scenarios/").data["results"] == []


# ---------------------------------------------------------------------------
# projections
# ---------------------------------------------------------------------------


def test_an_empty_workspace_gets_a_usable_error_not_a_stack_trace(tenant_context):
    """409 with an instruction, because the fix is an action the user can take."""
    _, client = tenant_context
    res = client.get(f"{BASE}/baseline/")
    assert res.status_code == 409
    assert "Add a current" in res.data["detail"]


def test_the_baseline_projection_returns_position_and_points(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.get(f"{BASE}/baseline/?months=24")
    assert res.status_code == 200
    assert res.data["position"]["currency"] == "USD"
    assert len(res.data["projection"]["points"]) == 24
    assert res.data["projection"]["assumptions"]


def test_the_baseline_horizon_is_bounded(tenant_context):
    _, client = tenant_context
    _account(client)
    assert client.get(f"{BASE}/baseline/?months=481").status_code == 400
    assert client.get(f"{BASE}/baseline/?months=0").status_code == 400
    assert client.get(f"{BASE}/baseline/?months=abc").status_code == 400


def test_running_a_scenario_returns_both_legs_and_a_delta(tenant_context):
    _, client = tenant_context
    _account(client)
    scenario = _scenario(client, horizon_months=36).data
    client.post(
        f"{BASE}/scenarios/{scenario['id']}/events/",
        {"kind": "salary_increase", "params": {"monthly_gross_increase_minor": 100_000}},
        format="json",
    )
    res = client.get(f"{BASE}/scenarios/{scenario['id']}/run/")
    assert res.status_code == 200
    assert len(res.data["baseline"]["points"]) == 36
    assert len(res.data["scenario"]["points"]) == 36
    assert res.data["delta"]["net_worth_minor"] > 0
    assert res.data["notes"]


def test_comparing_scenarios_preserves_the_requested_order(tenant_context):
    """A comparison table that reorders itself between requests is disorienting."""
    _, client = tenant_context
    _account(client)
    first = _scenario(client, name="A").data
    second = _scenario(client, name="B").data

    res = client.post(
        f"{BASE}/scenarios/compare/",
        {"scenario_ids": [second["id"], first["id"]]},
        format="json",
    )
    assert res.status_code == 200
    assert [r["scenario_name"] for r in res.data["runs"]] == ["B", "A"]


def test_comparing_an_unknown_scenario_is_a_404(tenant_context):
    _, client = tenant_context
    _account(client)
    res = client.post(
        f"{BASE}/scenarios/compare/",
        {"scenario_ids": ["00000000-0000-0000-0000-000000000000"]},
        format="json",
    )
    assert res.status_code == 404


def test_compare_requires_at_least_one_scenario(tenant_context):
    _, client = tenant_context
    res = client.post(f"{BASE}/scenarios/compare/", {"scenario_ids": []}, format="json")
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# assumptions and the event catalogue
# ---------------------------------------------------------------------------


def test_assumptions_are_readable_and_editable(tenant_context):
    _, client = tenant_context
    res = client.get(f"{BASE}/assumptions/")
    assert res.status_code == 200
    assert res.data["is_default"] is True

    patched = client.patch(f"{BASE}/assumptions/", {"annual_inflation": "0.0800"}, format="json")
    assert patched.status_code == 200
    assert patched.data["annual_inflation"] == "0.0800"


def test_the_event_catalogue_describes_every_declared_kind(tenant_context):
    """The scenario builder renders its forms from this, so a missing kind is a
    feature the user cannot reach.

    Derived from `EventKind` rather than a hardcoded count: this test's job is
    to catch a kind that exists but is not served, and a literal number just
    makes it fail every time the catalogue legitimately grows.
    """
    from apps.projections.events import EventKind

    _, client = tenant_context
    res = client.get(f"{BASE}/event-catalogue/")
    assert res.status_code == 200
    assert {e["kind"] for e in res.data["results"]} == set(EventKind.all())
    for entry in res.data["results"]:
        assert entry["label"]
        assert isinstance(entry["params"], list)


# ---------------------------------------------------------------------------
# calculators
# ---------------------------------------------------------------------------


def test_every_calculator_is_reachable_and_returns_assumptions(tenant_context):
    _, client = tenant_context
    payloads = {
        "mortgage": {
            "property_price_minor": 30_000_000,
            "deposit_minor": 6_000_000,
            "annual_rate": 0.055,
            "years": 25,
        },
        "loan": {"principal_minor": 5_000_000, "annual_rate": 0.14, "months": 60},
        "investment-growth": {
            "initial_minor": 1_000_000,
            "monthly_contribution_minor": 50_000,
            "annual_return": 0.07,
            "months": 120,
        },
        "savings-goal": {
            "target_minor": 1_000_000,
            "current_minor": 0,
            "monthly_contribution_minor": 50_000,
        },
        "retirement": {
            "current_pot_minor": 5_000_000,
            "monthly_contribution_minor": 50_000,
            "years_to_retirement": 25,
            "annual_return": 0.07,
        },
        "net-worth": {
            "assets_minor": 1_000_000,
            "liabilities_minor": 500_000,
            "monthly_saving_minor": 20_000,
            "annual_asset_return": 0.05,
            "months": 60,
        },
    }
    for slug, payload in payloads.items():
        res = client.post(f"{BASE}/calculators/{slug}/", payload, format="json")
        assert res.status_code == 200, f"{slug}: {res.data}"
        assert res.data["assumptions"], f"{slug} returned no assumptions"


def test_an_unknown_calculator_lists_the_ones_that_exist(tenant_context):
    _, client = tenant_context
    res = client.post(f"{BASE}/calculators/crystal-ball/", {}, format="json")
    assert res.status_code == 404
    assert "mortgage" in res.data["available"]


def test_a_calculator_input_error_is_a_400_with_the_reason(tenant_context):
    """Rates are fractions, and 7 instead of 0.07 is the classic caller error."""
    _, client = tenant_context
    res = client.post(
        f"{BASE}/calculators/loan/",
        {"principal_minor": 1_000_000, "annual_rate": 7.0, "months": 12},
        format="json",
    )
    assert res.status_code == 400
    assert "fractions" in res.data["detail"]


def test_a_deposit_larger_than_the_property_is_a_400(tenant_context):
    _, client = tenant_context
    res = client.post(
        f"{BASE}/calculators/mortgage/",
        {
            "property_price_minor": 1_000_000,
            "deposit_minor": 2_000_000,
            "annual_rate": 0.05,
            "years": 10,
        },
        format="json",
    )
    assert res.status_code == 400


def test_the_mortgage_endpoint_separates_payment_from_cost_of_ownership(tenant_context):
    _, client = tenant_context
    res = client.post(
        f"{BASE}/calculators/mortgage/",
        {
            "property_price_minor": 30_000_000,
            "deposit_minor": 6_000_000,
            "annual_rate": 0.055,
            "years": 25,
            "annual_tax_minor": 360_000,
            "annual_insurance_minor": 120_000,
        },
        format="json",
    )
    assert res.data["monthly_cost_minor"] > res.data["monthly_payment_minor"]


# ---------------------------------------------------------------------------
# isolation and auth
# ---------------------------------------------------------------------------


def test_the_api_requires_authentication():
    from rest_framework.test import APIClient

    assert APIClient().get(f"{BASE}/scenarios/").status_code in (401, 403)


def test_one_tenants_scenarios_are_invisible_to_another(tenant_context, django_user_model):
    from tests.conftest import _bearer_client
    from tests.factories import MembershipFactory

    _, client = tenant_context
    _scenario(client, name="Private plan")

    other_membership = MembershipFactory()
    other_client = _bearer_client(other_membership.user, tenant_id=other_membership.tenant_id)

    assert other_client.get(f"{BASE}/scenarios/").data["results"] == []
    assert len(client.get(f"{BASE}/scenarios/").data["results"]) == 1
