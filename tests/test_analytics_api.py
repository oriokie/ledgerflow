"""HTTP tests for the analytics drill-down endpoint: a single category's
monthly spend series."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _acct(client):
    return client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD"},
        format="json",
    ).data


def _cat(client, name="Food"):
    return client.post(
        "/api/v1/finance/categories/", {"name": name, "kind": "expense", "currency": "USD"}, format="json"
    ).data


def _expense(client, acct, cat, amount, occurred_at):
    return client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": amount,
            "occurred_at": occurred_at,
        },
        format="json",
    )


def test_category_trend_requires_category_id(tenant_context):
    _, client = tenant_context
    res = client.get("/api/v1/finance/category-trend/")
    assert res.status_code == 400


def test_category_trend_monthly_series(tenant_context):
    _, client = tenant_context
    acct = _acct(client)
    food = _cat(client, "Food")
    other = _cat(client, "Rent")

    # Two months of Food spend within the trailing year, plus noise in another category.
    _expense(client, acct, food, 20000, "2026-01-10T12:00:00Z")
    _expense(client, acct, food, 30000, "2026-03-05T12:00:00Z")
    _expense(client, acct, other, 99999, "2026-03-06T12:00:00Z")

    res = client.get(f"/api/v1/finance/category-trend/?category_id={food['id']}&months=12")
    assert res.status_code == 200
    series = res.data
    assert len(series) == 12
    # Dense, oldest-first, zero-filled; only Food counts.
    amounts = [row["amount_minor"] for row in series]
    assert sum(amounts) == 50000
    assert 20000 in amounts
    assert 30000 in amounts
    # Every row carries an ISO month start.
    assert all(row["period_start"][4] == "-" for row in series)
