"""PATCH /finance/transactions/<id>/ — payee_id set/clear/leave-alone semantics,
reached through the real DRF view (mirrors the category/memo coverage in
test_finance_modules_api.py, extended for payee_id once _txn_out started
including it)."""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.django_db


def _account(client, name="Checking", account_type="checking", currency="USD", opening=1_000_000):
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


def _category(client, name, kind, currency="USD"):
    return client.post(
        "/api/v1/finance/categories/", {"name": name, "kind": kind, "currency": currency}, format="json"
    ).data


def _payee(client, name):
    return client.post("/api/v1/finance/payees/", {"name": name}, format="json").data


def _expense(client, acct, cat):
    return client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": 5000,
            "occurred_at": "2026-01-01T00:00:00Z",
        },
        format="json",
    ).data


def test_patch_transaction_sets_payee_and_it_round_trips(tenant_context):
    membership, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Groceries", "expense")
    payee = _payee(client, "Trader Joe's")
    txn = _expense(client, acct, cat)
    assert txn["payee_id"] is None

    resp = client.patch(
        f"/api/v1/finance/transactions/{txn['id']}/", {"payee_id": payee["id"]}, format="json"
    )
    assert resp.status_code == 200, resp.data
    assert str(resp.data["payee_id"]) == str(payee["id"])

    fetched = client.get(f"/api/v1/finance/transactions/{txn['id']}/")
    assert str(fetched.data["payee_id"]) == str(payee["id"])


def test_patch_transaction_clears_payee_with_explicit_null(tenant_context):
    membership, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Groceries", "expense")
    payee = _payee(client, "Trader Joe's")
    txn = _expense(client, acct, cat)
    client.patch(f"/api/v1/finance/transactions/{txn['id']}/", {"payee_id": payee["id"]}, format="json")

    resp = client.patch(f"/api/v1/finance/transactions/{txn['id']}/", {"payee_id": None}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.data["payee_id"] is None


def test_patch_transaction_omits_payee_leaves_it_alone(tenant_context):
    membership, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Groceries", "expense")
    payee = _payee(client, "Trader Joe's")
    txn = _expense(client, acct, cat)
    client.patch(f"/api/v1/finance/transactions/{txn['id']}/", {"payee_id": payee["id"]}, format="json")

    resp = client.patch(f"/api/v1/finance/transactions/{txn['id']}/", {"memo": "new memo"}, format="json")
    assert resp.status_code == 200, resp.data
    assert str(resp.data["payee_id"]) == str(payee["id"])
    assert resp.data["memo"] == "new memo"


def test_patch_transaction_unknown_payee_id_rejected(tenant_context):
    membership, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Groceries", "expense")
    txn = _expense(client, acct, cat)

    resp = client.patch(
        f"/api/v1/finance/transactions/{txn['id']}/", {"payee_id": str(uuid.uuid4())}, format="json"
    )
    assert resp.status_code == 400
