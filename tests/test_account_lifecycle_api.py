"""HTTP tests for the account lifecycle endpoints: opening balances, settings
updates, and the archive/unarchive round trip."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _create(client, **overrides):
    payload = {"name": "Checking", "account_type": "checking", "currency": "USD"}
    payload.update(overrides)
    return client.post("/api/v1/finance/accounts/", payload, format="json")


def test_create_with_opening_balance_returns_the_real_balance(tenant_context):
    _, client = tenant_context
    resp = _create(client, name="Everyday Checking", opening_balance_minor=3_250_00)

    assert resp.status_code == 201, resp.data
    # The response balance comes from the ledger, not from the request body.
    assert resp.data["balance_minor"] == 3_250_00


def test_credit_card_opening_balance_is_recorded_as_owed(tenant_context):
    _, client = tenant_context
    resp = _create(client, name="Travel Card", account_type="credit_card", opening_balance_minor=1_200_00)

    assert resp.status_code == 201, resp.data
    assert resp.data["balance_minor"] == 1_200_00

    net = client.get("/api/v1/finance/net-worth/")
    usd = next(r for r in net.data if r["currency"] == "USD")
    assert usd["liabilities_minor"] == 1_200_00


def test_opening_balance_reaches_net_worth(tenant_context):
    _, client = tenant_context
    _create(client, name="Savings", account_type="savings", opening_balance_minor=10_000_00)

    net = client.get("/api/v1/finance/net-worth/")
    usd = next(r for r in net.data if r["currency"] == "USD")
    assert usd["assets_minor"] == 10_000_00
    assert usd["net_minor"] == 10_000_00


def test_negative_opening_balance_is_rejected_by_the_serializer(tenant_context):
    _, client = tenant_context
    resp = _create(client, opening_balance_minor=-500)
    assert resp.status_code == 400


def test_presentation_fields_round_trip(tenant_context):
    _, client = tenant_context
    created = _create(client, color="#5558d9", icon="landmark", notes="Joint account.")
    assert created.status_code == 201, created.data

    listing = client.get("/api/v1/finance/accounts/")
    row = listing.data[0]
    assert row["color"] == "#5558d9"
    assert row["icon"] == "landmark"
    assert row["notes"] == "Joint account."


def test_patch_updates_settings_but_ignores_immutable_fields(tenant_context):
    _, client = tenant_context
    account_id = _create(client).data["id"]

    resp = client.patch(
        f"/api/v1/finance/accounts/{account_id}/",
        {"name": "Renamed", "is_hidden": True, "currency": "EUR", "account_type": "savings"},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["name"] == "Renamed"
    assert resp.data["is_hidden"] is True
    # Currency and type are baked into posted ledger lines — unchanged.
    assert resp.data["currency"] == "USD"
    assert resp.data["account_type"] == "checking"


def test_excluding_an_account_removes_it_from_net_worth_only(tenant_context):
    _, client = tenant_context
    _create(client, name="Personal", opening_balance_minor=2_000_00)
    business = _create(client, name="Business", opening_balance_minor=9_000_00).data["id"]

    client.patch(
        f"/api/v1/finance/accounts/{business}/", {"include_in_net_worth": False}, format="json"
    )

    net = client.get("/api/v1/finance/net-worth/")
    usd = next(r for r in net.data if r["currency"] == "USD")
    assert usd["assets_minor"] == 2_000_00

    # The account and its money still exist and are still listed.
    listing = client.get("/api/v1/finance/accounts/")
    excluded = next(a for a in listing.data if a["id"] == business)
    assert excluded["balance_minor"] == 9_000_00


def test_delete_archives_rather_than_destroys(tenant_context):
    _, client = tenant_context
    account_id = _create(client, name="Old Card", opening_balance_minor=300_00).data["id"]

    resp = client.delete(f"/api/v1/finance/accounts/{account_id}/")
    assert resp.status_code == 200, resp.data
    assert resp.data["is_archived"] is True

    # Gone from the default list...
    assert client.get("/api/v1/finance/accounts/").data == []
    # ...but still retrievable, with its history intact.
    archived = client.get("/api/v1/finance/accounts/?include_archived=1").data
    assert len(archived) == 1
    assert archived[0]["balance_minor"] == 300_00


def test_archived_account_can_be_reopened(tenant_context):
    _, client = tenant_context
    account_id = _create(client, opening_balance_minor=100_00).data["id"]
    client.delete(f"/api/v1/finance/accounts/{account_id}/")

    resp = client.post(f"/api/v1/finance/accounts/{account_id}/unarchive/")
    assert resp.status_code == 200, resp.data
    assert resp.data["is_archived"] is False

    listing = client.get("/api/v1/finance/accounts/")
    assert len(listing.data) == 1
    assert listing.data[0]["balance_minor"] == 100_00
