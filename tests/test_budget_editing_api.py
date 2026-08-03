"""HTTP tests for the budget editing surface added for the budgeting screens:
in-place line edits, line removal, budget deletion, and the period window now
included in the status payload."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _setup(client):
    acct = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD"},
        format="json",
    ).data
    food = client.post(
        "/api/v1/finance/categories/", {"name": "Food", "kind": "expense", "currency": "USD"}, format="json"
    ).data
    budget = client.post(
        "/api/v1/budgeting/budgets/",
        {"name": "Monthly", "currency": "USD", "starts_on": "2026-01-01", "period": "monthly"},
        format="json",
    ).data
    line = client.post(
        f"/api/v1/budgeting/budgets/{budget['id']}/lines/",
        {"category_id": food["id"], "limit_minor": 50000},
        format="json",
    ).data
    return acct, food, budget, line


def test_status_includes_period_window(tenant_context):
    _, client = tenant_context
    _, _, budget, _ = _setup(client)
    st = client.get(f"/api/v1/budgeting/budgets/{budget['id']}/status/?as_of=2026-01-15")
    assert st.status_code == 200
    assert st.data["as_of"] == "2026-01-15"
    assert st.data["period_start"] == "2026-01-01"
    assert st.data["period_end"] == "2026-02-01"


def test_update_line_limit(tenant_context):
    _, _, budget, line = _setup(client := tenant_context[1])
    res = client.patch(
        f"/api/v1/budgeting/budgets/{budget['id']}/lines/{line['id']}/",
        {"limit_minor": 80000},
        format="json",
    )
    assert res.status_code == 200, res.data
    assert res.data["limit_minor"] == 80000

    st = client.get(f"/api/v1/budgeting/budgets/{budget['id']}/status/?as_of=2026-01-15")
    assert st.data["lines"][0]["effective_limit_minor"] == 80000


def test_update_line_rejects_negative(tenant_context):
    _, _, budget, line = _setup(client := tenant_context[1])
    res = client.patch(
        f"/api/v1/budgeting/budgets/{budget['id']}/lines/{line['id']}/",
        {"limit_minor": -5},
        format="json",
    )
    assert res.status_code == 400


def test_remove_line_and_readd(tenant_context):
    _, food, budget, line = _setup(client := tenant_context[1])
    res = client.delete(f"/api/v1/budgeting/budgets/{budget['id']}/lines/{line['id']}/")
    assert res.status_code == 204

    st = client.get(f"/api/v1/budgeting/budgets/{budget['id']}/status/?as_of=2026-01-15")
    assert st.data["lines"] == []

    # The (budget, category) uniqueness is scoped to live rows, so re-adding works.
    again = client.post(
        f"/api/v1/budgeting/budgets/{budget['id']}/lines/",
        {"category_id": food["id"], "limit_minor": 12345},
        format="json",
    )
    assert again.status_code == 201, again.data


def test_delete_budget_removes_from_list(tenant_context):
    _, _, budget, _ = _setup(client := tenant_context[1])
    res = client.delete(f"/api/v1/budgeting/budgets/{budget['id']}/")
    assert res.status_code == 204

    listing = client.get("/api/v1/budgeting/budgets/")
    assert all(b["id"] != budget["id"] for b in listing.data)
