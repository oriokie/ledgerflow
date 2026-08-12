"""End-to-end HTTP tests for the new feature endpoints: goals, notifications,
splits, bills, export, import, forecast — through real DRF views, permissions,
and RLS binding. Includes a cross-tenant isolation check for goals."""

from __future__ import annotations

import pytest

from tests.conftest import _bearer_client
from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


def _mk_account(client, name="Checking", currency="USD", account_type="checking", opening=1_000_000):
    # Funded: a workspace blocks manual overdrafts by default, so an account
    # with nothing in it cannot record an expense.
    return client.post(
        "/api/v1/finance/accounts/",
        {
            "name": name,
            "account_type": account_type,
            "currency": currency,
            "opening_balance_minor": opening,
        },
        format="json",
    ).data


def _mk_category(client, name="Groceries", kind="expense", currency="USD"):
    return client.post(
        "/api/v1/finance/categories/",
        {"name": name, "kind": kind, "currency": currency},
        format="json",
    ).data


# ------------------------------------------------------------------- goals
def test_goal_create_contribute_and_progress(tenant_context):
    _, client = tenant_context
    goal = client.post(
        "/api/v1/goals/goals/",
        {"name": "Vacation", "currency": "USD", "target_minor": 100000},
        format="json",
    )
    assert goal.status_code == 201, goal.data
    goal_id = goal.data["id"]

    contrib = client.post(
        f"/api/v1/goals/goals/{goal_id}/contributions/",
        {"amount_minor": 40000},
        format="json",
    )
    assert contrib.status_code == 201, contrib.data
    assert contrib.data["goal"]["saved_minor"] == 40000
    assert contrib.data["goal"]["percent"] == 40.0


def test_goal_cross_tenant_isolation():
    m_a = MembershipFactory()
    m_b = MembershipFactory()
    client_a = _bearer_client(m_a.user, tenant_id=m_a.tenant_id)
    client_b = _bearer_client(m_b.user, tenant_id=m_b.tenant_id)

    created = client_a.post(
        "/api/v1/goals/goals/",
        {"name": "A's goal", "currency": "USD", "target_minor": 5000},
        format="json",
    )
    assert created.status_code == 201
    goal_id = created.data["id"]

    # tenant B must not see or fetch tenant A's goal
    assert client_b.get("/api/v1/goals/goals/").data == []
    assert client_b.get(f"/api/v1/goals/goals/{goal_id}/").status_code == 404


# ------------------------------------------------------------------- splits
def test_split_endpoint(tenant_context):
    _, client = tenant_context
    acct = _mk_account(client)
    groceries = _mk_category(client, "Groceries")
    household = _mk_category(client, "Household")
    txn = client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": groceries["id"],
            "amount_minor": 10000,
            "occurred_at": "2026-01-05T12:00:00Z",
        },
        format="json",
    ).data
    resp = client.post(
        f"/api/v1/finance/transactions/{txn['id']}/split/",
        {
            "parts": [
                {"category_id": groceries["id"], "amount_minor": 6000},
                {"category_id": household["id"], "amount_minor": 4000},
            ]
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert len(resp.data) == 2


# -------------------------------------------------------------------- bills
def test_bill_create_and_pay(tenant_context):
    _, client = tenant_context
    acct = _mk_account(client)
    rent = _mk_category(client, "Rent")
    bill = client.post(
        "/api/v1/finance/bills/",
        {
            "name": "Rent",
            "amount_minor": 150000,
            "currency": "USD",
            "due_on": "2026-02-01",
            "category_id": rent["id"],
        },
        format="json",
    )
    assert bill.status_code == 201, bill.data
    bill_id = bill.data["id"]

    upcoming = client.get("/api/v1/finance/bills/?upcoming=365")
    assert any(b["id"] == bill_id for b in upcoming.data)

    paid = client.post(
        f"/api/v1/finance/bills/{bill_id}/pay/",
        {"from_account_id": acct["id"]},
        format="json",
    )
    assert paid.status_code == 200, paid.data
    assert paid.data["bill"]["status"] == "paid"
    assert paid.data["settling_transaction_id"] is not None


# ------------------------------------------------------------ notifications
def test_notifications_inbox(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/notifications/")
    assert resp.status_code == 200
    assert "results" in resp.data
    assert resp.data["unread_count"] == 0


# ------------------------------------------------------------------ export
def test_transaction_export_csv(tenant_context):
    _, client = tenant_context
    acct = _mk_account(client)
    cat = _mk_category(client)
    client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": 4200,
            "occurred_at": "2026-01-05T12:00:00Z",
            "memo": "Coffee",
        },
        format="json",
    )
    resp = client.get("/api/v1/finance/transactions/export/")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv"
    body = b"".join(resp.streaming_content).decode()
    assert "Coffee" in body
    assert body.startswith("id,occurred_at,amount_minor")


# ------------------------------------------------------------------ import
def test_transaction_import_csv(tenant_context):
    _, client = tenant_context
    acct = _mk_account(client)
    csv_text = "date,amount,description,external_id\n2026-01-05,-42.50,Coffee shop,imp-1\n"
    resp = client.post(
        "/api/v1/finance/transactions/import/",
        {"account_id": acct["id"], "content": csv_text},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["imported"] == 1


# ---------------------------------------------------------------- forecast
def test_forecast_endpoint(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/intelligence/forecast/")
    assert resp.status_code == 200
    assert "points" in resp.data


def test_voided_income_leaves_the_spending_trend(tenant_context):
    """Deleting June income must drop it from the dashboard / analytics chart.

    The chart used to sum every row including voids, so a deleted salary
    lingered as a bar after the ledger list had already hidden it.
    """
    _, client = tenant_context
    account = _mk_account(client)
    salary = _mk_category(client, name="Salary", kind="income")
    created = client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "income",
            "financial_account_id": account["id"],
            "category_id": salary["id"],
            "amount_minor": 250_000,
            "occurred_at": "2026-06-15T12:00:00Z",
        },
        format="json",
    )
    assert created.status_code in (200, 201), created.data

    before = client.get("/api/v1/intelligence/spending-trend/?months=6").data
    june = next(p for p in before if p["period_start"].startswith("2026-06"))
    assert june["income_minor"] == 250_000

    voided = client.post(f"/api/v1/finance/transactions/{created.data['id']}/void/", {}, format="json")
    assert voided.status_code == 200, voided.data

    after = client.get("/api/v1/intelligence/spending-trend/?months=6").data
    june_after = next(p for p in after if p["period_start"].startswith("2026-06"))
    assert june_after["income_minor"] == 0


def test_net_worth_history_endpoint(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/intelligence/net-worth-history/?months=3")
    assert resp.status_code == 200
    assert isinstance(resp.data, list)
    assert len(resp.data) == 3


def test_goal_contribution_history(tenant_context):
    """The contributions endpoint lists a goal's contributions, most recent
    first — the momentum timeline the goal screen shows."""
    _, client = tenant_context
    goal = client.post(
        "/api/v1/goals/goals/",
        {"name": "Vacation", "currency": "USD", "target_minor": 100000},
        format="json",
    ).data
    goal_id = goal["id"]

    client.post(
        f"/api/v1/goals/goals/{goal_id}/contributions/",
        {"amount_minor": 10000, "occurred_on": "2026-01-05", "memo": "January"},
        format="json",
    )
    client.post(
        f"/api/v1/goals/goals/{goal_id}/contributions/",
        {"amount_minor": 25000, "occurred_on": "2026-02-05", "memo": "February"},
        format="json",
    )

    history = client.get(f"/api/v1/goals/goals/{goal_id}/contributions/")
    assert history.status_code == 200
    assert len(history.data) == 2
    # Most recent first
    assert history.data[0]["amount_minor"] == 25000
    assert history.data[0]["memo"] == "February"
    assert history.data[1]["amount_minor"] == 10000


def test_bill_cancel(tenant_context):
    """DELETE cancels a bill: it leaves the upcoming list and reads as cancelled."""
    _, client = tenant_context
    _mk_account(client)
    rent = _mk_category(client, "Rent")
    bill = client.post(
        "/api/v1/finance/bills/",
        {
            "name": "Gym",
            "amount_minor": 5000,
            "currency": "USD",
            "due_on": "2026-02-01",
            "category_id": rent["id"],
        },
        format="json",
    ).data
    bill_id = bill["id"]

    assert any(b["id"] == bill_id for b in client.get("/api/v1/finance/bills/?upcoming=365").data)

    cancelled = client.delete(f"/api/v1/finance/bills/{bill_id}/")
    assert cancelled.status_code == 204

    # Gone from the upcoming/overdue list.
    assert all(b["id"] != bill_id for b in client.get("/api/v1/finance/bills/?upcoming=365").data)
    # Still retrievable, now cancelled (history retained, not hard-deleted).
    detail = client.get(f"/api/v1/finance/bills/{bill_id}/")
    assert detail.status_code == 200
    assert detail.data["status"] == "cancelled"
