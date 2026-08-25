"""End-to-end HTTP tests for the newer finance API surface: wallets, payees,
tags, attachments, transaction editing, and cursor pagination — reached
through real DRF views, permissions, and RLS binding."""

from __future__ import annotations

import pytest

from apps.tenancy.models import Role
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


def _account(client, name="Checking", account_type="checking", currency="USD", opening=1_000_000):
    """A funded account, because that is what a real one is.

    A workspace blocks manual overdrafts by default, so an account with nothing
    in it cannot record an expense — which is correct behaviour and a useless
    fixture. Pass `opening=0` where the balance itself is what's being asserted.
    """
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


# --------------------------------------------------------------- wallets
def test_wallet_create_and_balances(tenant_context):
    membership, client = tenant_context
    # Unfunded: this asserts the per-currency roll-up exactly, and it only
    # posts income, so there is nothing for the overdraft guard to refuse.
    usd = _account(client, "US Checking", currency="USD", opening=0)
    eur = _account(client, "EU Checking", currency="EUR", opening=0)
    usd_income = _category(client, "USD In", "income", "USD")
    eur_income = _category(client, "EUR In", "income", "EUR")

    wallet = client.post("/api/v1/finance/wallets/", {"name": "Global"}, format="json")
    assert wallet.status_code == 201, wallet.data
    wallet_id = wallet.data["id"]

    for acct_id in (usd["id"], eur["id"]):
        resp = client.post(
            "/api/v1/finance/wallets/assign-account/",
            {"financial_account_id": acct_id, "wallet_id": wallet_id},
            format="json",
        )
        assert resp.status_code == 200, resp.data

    client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "income",
            "financial_account_id": usd["id"],
            "category_id": usd_income["id"],
            "amount_minor": 10000,
            "occurred_at": "2026-01-01T00:00:00Z",
        },
        format="json",
    )
    client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "income",
            "financial_account_id": eur["id"],
            "category_id": eur_income["id"],
            "amount_minor": 5000,
            "occurred_at": "2026-01-01T00:00:00Z",
        },
        format="json",
    )

    detail = client.get(f"/api/v1/finance/wallets/{wallet_id}/")
    assert detail.status_code == 200
    balances = {b["currency"]: b["balance_minor"] for b in detail.data["balances"]}
    assert balances == {"USD": 10000, "EUR": 5000}


def test_wallet_unassign_account(tenant_context):
    membership, client = tenant_context
    acct = _account(client)
    wallet = client.post("/api/v1/finance/wallets/", {"name": "Travel"}, format="json").data
    client.post(
        "/api/v1/finance/wallets/assign-account/",
        {"financial_account_id": acct["id"], "wallet_id": wallet["id"]},
        format="json",
    )
    resp = client.post(
        "/api/v1/finance/wallets/assign-account/", {"financial_account_id": acct["id"]}, format="json"
    )
    assert resp.status_code == 200
    assert resp.data["wallet_id"] is None


def test_viewer_cannot_create_wallet(tenant_context):
    owner_membership, _owner_client = tenant_context
    viewer = MembershipFactory(tenant=owner_membership.tenant, role=Role.VIEWER)
    viewer_client = _bearer_client(viewer.user, tenant_id=viewer.tenant_id)
    resp = viewer_client.post("/api/v1/finance/wallets/", {"name": "X"}, format="json")
    assert resp.status_code == 403


# --------------------------------------------------------------- payees
def test_payee_create_and_list(tenant_context):
    membership, client = tenant_context
    resp = client.post("/api/v1/finance/payees/", {"name": "Trader Joe's"}, format="json")
    assert resp.status_code == 201, resp.data
    assert resp.data["normalized_name"] == "trader joe's"

    listing = client.get("/api/v1/finance/payees/")
    assert listing.status_code == 200
    assert len(listing.data) == 1


def test_duplicate_payee_returns_conflict(tenant_context):
    membership, client = tenant_context
    client.post("/api/v1/finance/payees/", {"name": "Store"}, format="json")
    resp = client.post("/api/v1/finance/payees/", {"name": "store"}, format="json")
    assert resp.status_code == 409


# --------------------------------------------------------------- tags
def test_tag_create_and_attach_to_transaction(tenant_context):
    membership, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Groceries", "expense")
    txn = client.post(
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

    tag1 = client.post("/api/v1/finance/tags/", {"name": "business"}, format="json").data
    tag2 = client.post("/api/v1/finance/tags/", {"name": "reimbursable"}, format="json").data

    resp = client.put(
        f"/api/v1/finance/transactions/{txn['id']}/tags/",
        {"tag_ids": [tag1["id"], tag2["id"]]},
        format="json",
    )
    assert resp.status_code == 200
    assert {t["name"] for t in resp.data} == {"business", "reimbursable"}

    # remove one
    resp2 = client.put(
        f"/api/v1/finance/transactions/{txn['id']}/tags/", {"tag_ids": [tag1["id"]]}, format="json"
    )
    assert {t["name"] for t in resp2.data} == {"business"}


def test_attach_unknown_tag_id_rejected(tenant_context):
    membership, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Groceries", "expense")
    txn = client.post(
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
    resp = client.put(
        f"/api/v1/finance/transactions/{txn['id']}/tags/",
        {"tag_ids": ["00000000-0000-0000-0000-000000000000"]},
        format="json",
    )
    assert resp.status_code == 400


# --------------------------------------------------------------- attachments
def test_attachment_upload_flow(tenant_context):
    membership, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Groceries", "expense")
    txn = client.post(
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

    req = client.post(
        f"/api/v1/finance/transactions/{txn['id']}/attachments/request-upload/",
        {"filename": "receipt.pdf", "content_type": "application/pdf", "byte_size": 2048},
        format="json",
    )
    assert req.status_code == 201, req.data
    assert req.data["status"] == "pending"
    attachment_id = req.data["id"]

    confirm = client.post(
        f"/api/v1/finance/attachments/{attachment_id}/confirm/", {"checksum": "abc"}, format="json"
    )
    assert confirm.status_code == 200
    assert confirm.data["status"] == "uploaded"

    listing = client.get(f"/api/v1/finance/transactions/{txn['id']}/attachments/")
    assert listing.status_code == 200
    assert len(listing.data) == 1


def test_attachment_oversized_rejected(tenant_context):
    membership, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Groceries", "expense")
    txn = client.post(
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
    resp = client.post(
        f"/api/v1/finance/transactions/{txn['id']}/attachments/request-upload/",
        {"filename": "huge.mp4", "content_type": "video/mp4", "byte_size": 999_999_999},
        format="json",
    )
    assert resp.status_code == 422


# --------------------------------------------------------------- transaction editing
def test_patch_transaction_recategorize_and_memo(tenant_context):
    membership, client = tenant_context
    acct = _account(client)
    groceries = _category(client, "Groceries", "expense")
    dining = _category(client, "Dining", "expense")
    txn = client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": groceries["id"],
            "amount_minor": 5000,
            "occurred_at": "2026-01-01T00:00:00Z",
            "memo": "old",
        },
        format="json",
    ).data

    resp = client.patch(
        f"/api/v1/finance/transactions/{txn['id']}/",
        {"category_id": dining["id"], "memo": "new"},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["category_id"] == dining["id"]
    assert resp.data["memo"] == "new"
    assert resp.data["amount_minor"] == -5000  # untouched


def test_patch_transaction_wrong_category_kind_rejected(tenant_context):
    membership, client = tenant_context
    acct = _account(client)
    groceries = _category(client, "Groceries", "expense")
    salary = _category(client, "Salary", "income")
    txn = client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": groceries["id"],
            "amount_minor": 5000,
            "occurred_at": "2026-01-01T00:00:00Z",
        },
        format="json",
    ).data
    resp = client.patch(
        f"/api/v1/finance/transactions/{txn['id']}/", {"category_id": salary["id"]}, format="json"
    )
    assert resp.status_code == 422


def test_get_single_transaction(tenant_context):
    membership, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Groceries", "expense")
    txn = client.post(
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
    resp = client.get(f"/api/v1/finance/transactions/{txn['id']}/")
    assert resp.status_code == 200
    assert resp.data["id"] == txn["id"]


def test_viewer_cannot_patch_transaction(tenant_context):
    owner_membership, owner_client = tenant_context
    acct = _account(owner_client)
    cat = _category(owner_client, "Groceries", "expense")
    txn = owner_client.post(
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
    viewer = MembershipFactory(tenant=owner_membership.tenant, role=Role.VIEWER)
    viewer_client = _bearer_client(viewer.user, tenant_id=viewer.tenant_id)
    resp = viewer_client.patch(f"/api/v1/finance/transactions/{txn['id']}/", {"memo": "hack"}, format="json")
    assert resp.status_code == 403


# --------------------------------------------------------------- pagination
def test_transaction_list_is_paginated(tenant_context):
    membership, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Groceries", "expense")
    for i in range(30):
        client.post(
            "/api/v1/finance/transactions/",
            {
                "type": "expense",
                "financial_account_id": acct["id"],
                "category_id": cat["id"],
                "amount_minor": 100 + i,
                "occurred_at": "2026-01-01T00:00:00Z",
            },
            format="json",
        )
    first_page = client.get("/api/v1/finance/transactions/")
    assert first_page.status_code == 200
    assert "results" in first_page.data
    assert "next" in first_page.data
    assert len(first_page.data["results"]) == 25  # default page_size
    assert first_page.data["next"] is not None

    second_page = client.get(first_page.data["next"])
    assert second_page.status_code == 200
    assert len(second_page.data["results"]) == 5  # remaining 5 of 30


# ------------------------------------------------------ bulk actions + receipts
def _expense_txn(client, acct, cat, amount=5000, when="2026-01-01T00:00:00Z"):
    return client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": amount,
            "occurred_at": when,
        },
        format="json",
    ).data


def _income_txn(client, acct, cat, amount=9000, when="2026-01-02T00:00:00Z"):
    return client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "income",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": amount,
            "occurred_at": when,
        },
        format="json",
    ).data


def test_bulk_categorize_applies_to_all(tenant_context):
    _, client = tenant_context
    acct = _account(client)
    groceries = _category(client, "Groceries", "expense")
    dining = _category(client, "Dining", "expense")
    t1 = _expense_txn(client, acct, groceries)
    t2 = _expense_txn(client, acct, groceries)

    res = client.post(
        "/api/v1/finance/transactions/bulk/",
        {"action": "categorize", "ids": [t1["id"], t2["id"]], "category_id": dining["id"]},
        format="json",
    )
    assert res.status_code == 200, res.data
    assert res.data == {"requested": 2, "updated": 2, "failed": []}

    for tid in (t1["id"], t2["id"]):
        got = client.get(f"/api/v1/finance/transactions/{tid}/")
        assert got.data["category_id"] == dining["id"]


def test_bulk_categorize_reports_partial_failure(tenant_context):
    _, client = tenant_context
    acct = _account(client)
    groceries = _category(client, "Groceries", "expense")
    salary = _category(client, "Salary", "income")
    expense = _expense_txn(client, acct, groceries)
    income = _income_txn(client, acct, salary)

    # An expense category can't apply to an income row → that row fails, the
    # other succeeds, and nothing aborts the batch.
    res = client.post(
        "/api/v1/finance/transactions/bulk/",
        {"action": "categorize", "ids": [expense["id"], income["id"]], "category_id": groceries["id"]},
        format="json",
    )
    assert res.status_code == 200, res.data
    assert res.data["requested"] == 2
    assert res.data["updated"] == 1
    assert [f["id"] for f in res.data["failed"]] == [str(income["id"])]


def test_bulk_void_and_missing_ids(tenant_context):
    _, client = tenant_context
    acct = _account(client)
    groceries = _category(client, "Groceries", "expense")
    t1 = _expense_txn(client, acct, groceries)
    missing = "00000000-0000-0000-0000-000000000000"

    res = client.post(
        "/api/v1/finance/transactions/bulk/",
        {"action": "void", "ids": [t1["id"], missing]},
        format="json",
    )
    assert res.status_code == 200, res.data
    assert res.data["updated"] == 1
    assert any(f["id"] == missing and f["error"] == "not found" for f in res.data["failed"])

    got = client.get(f"/api/v1/finance/transactions/{t1['id']}/")
    assert got.data["status"] == "void"


def test_bulk_rejects_empty_ids(tenant_context):
    _, client = tenant_context
    res = client.post(
        "/api/v1/finance/transactions/bulk/",
        {"action": "void", "ids": []},
        format="json",
    )
    assert res.status_code == 400


def test_receipt_direct_upload_and_download(tenant_context):
    """In environments without presigning (tests use InMemoryStorage), the
    request-upload step returns no upload_url and the client uploads the bytes
    to our direct endpoint; the file is then downloadable."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    _, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Groceries", "expense")
    txn = _expense_txn(client, acct, cat)
    blob = b"%PDF-1.4 fake receipt bytes"

    req = client.post(
        f"/api/v1/finance/transactions/{txn['id']}/attachments/request-upload/",
        {"filename": "receipt.pdf", "content_type": "application/pdf", "byte_size": len(blob)},
        format="json",
    )
    assert req.status_code == 201, req.data
    assert req.data["upload_url"] is None  # no presign in this environment
    attachment_id = req.data["id"]

    up = client.post(
        f"/api/v1/finance/attachments/{attachment_id}/upload/",
        {"file": SimpleUploadedFile("receipt.pdf", blob, content_type="application/pdf")},
        format="multipart",
    )
    assert up.status_code == 200, up.data
    assert up.data["status"] == "uploaded"
    assert up.data["byte_size"] == len(blob)
    assert up.data["download_url"] and up.data["download_url"].endswith(
        f"/attachments/{attachment_id}/download/"
    )

    dl = client.get(f"/api/v1/finance/attachments/{attachment_id}/download/")
    assert dl.status_code == 200
    body = b"".join(dl.streaming_content) if hasattr(dl, "streaming_content") else dl.content
    assert body == blob


def test_receipt_download_missing_before_upload(tenant_context):
    _, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Groceries", "expense")
    txn = _expense_txn(client, acct, cat)
    req = client.post(
        f"/api/v1/finance/transactions/{txn['id']}/attachments/request-upload/",
        {"filename": "r.pdf", "content_type": "application/pdf", "byte_size": 10},
        format="json",
    ).data
    # Not yet uploaded → no download available, and no download_url exposed.
    assert req["download_url"] is None
    dl = client.get(f"/api/v1/finance/attachments/{req['id']}/download/")
    assert dl.status_code == 422


# --------------------------------------------------- recurring pause / cancel
def test_recurring_serializer_includes_label_fields(tenant_context):
    _, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Streaming", "expense")
    created = client.post(
        "/api/v1/finance/recurring/",
        {
            "txn_type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": 1500,
            "currency": "USD",
            "frequency": "monthly",
            "starts_on": "2026-01-01",
            "memo": "Netflix",
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    assert created.data["memo"] == "Netflix"
    assert str(created.data["category_id"]) == str(cat["id"])
    assert str(created.data["financial_account_id"]) == str(acct["id"])


def test_recurring_transfer_api_preserves_both_accounts(tenant_context):
    _, client = tenant_context
    source = _account(client, name="Checking")
    destination = _account(client, name="Savings", account_type="savings")
    created = client.post(
        "/api/v1/finance/recurring/",
        {
            "txn_type": "transfer",
            "financial_account_id": source["id"],
            "counter_account_id": destination["id"],
            "amount_minor": 20_000,
            "currency": "USD",
            "frequency": "monthly",
            "starts_on": "2026-01-01",
            "memo": "Monthly savings",
        },
        format="json",
    )
    assert created.status_code == 201, created.data
    assert str(created.data["financial_account_id"]) == str(source["id"])
    assert str(created.data["counter_account_id"]) == str(destination["id"])
    assert created.data["category_id"] is None

    same_account = client.post(
        "/api/v1/finance/recurring/",
        {
            "txn_type": "transfer",
            "financial_account_id": source["id"],
            "counter_account_id": source["id"],
            "amount_minor": 20_000,
            "currency": "USD",
            "frequency": "monthly",
            "starts_on": "2026-01-01",
        },
        format="json",
    )
    assert same_account.status_code == 422


def test_recurring_pause_and_cancel(tenant_context):
    _, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Streaming", "expense")
    rec = client.post(
        "/api/v1/finance/recurring/",
        {
            "txn_type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": 1500,
            "currency": "USD",
            "frequency": "monthly",
            "starts_on": "2026-01-01",
            "memo": "Netflix",
        },
        format="json",
    ).data
    rec_id = rec["id"]

    # Pause: stays on the list (so it can be resumed) but is marked inactive.
    paused = client.patch(f"/api/v1/finance/recurring/{rec_id}/", {"is_active": False}, format="json")
    assert paused.status_code == 200
    assert paused.data["is_active"] is False
    listed = client.get("/api/v1/finance/recurring/").data
    paused_row = next(r for r in listed if r["id"] == rec_id)
    assert paused_row["is_active"] is False

    # Resume.
    resumed = client.patch(f"/api/v1/finance/recurring/{rec_id}/", {"is_active": True}, format="json")
    assert resumed.status_code == 200
    assert any(r["id"] == rec_id and r["is_active"] for r in client.get("/api/v1/finance/recurring/").data)

    # Cancel: soft-deleted, gone from the list for good.
    cancelled = client.delete(f"/api/v1/finance/recurring/{rec_id}/")
    assert cancelled.status_code == 204
    assert all(r["id"] != rec_id for r in client.get("/api/v1/finance/recurring/").data)
    assert (
        client.patch(f"/api/v1/finance/recurring/{rec_id}/", {"is_active": True}, format="json").status_code
        == 404
    )


def test_recurring_can_be_edited_after_it_has_posted(tenant_context):
    """A schedule is a plan; correcting it changes what happens next.

    The rent went up and the cadence moved from monthly to quarterly. Both are
    edits to the plan, and neither is allowed to touch what the template has
    already posted.
    """
    _, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Housing", "expense")
    rec = client.post(
        "/api/v1/finance/recurring/",
        {
            "txn_type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": 120_000,
            "currency": "USD",
            "frequency": "monthly",
            "starts_on": "2026-01-01",
            "memo": "Rent",
        },
        format="json",
    ).data
    rec_id = rec["id"]

    edited = client.patch(
        f"/api/v1/finance/recurring/{rec_id}/",
        {"amount_minor": 135_000, "memo": "Rent (rise from Jan)"},
        format="json",
    )
    assert edited.status_code == 200, edited.data
    assert edited.data["amount_minor"] == 135_000
    assert edited.data["memo"] == "Rent (rise from Jan)"
    # A partial edit leaves everything it didn't mention alone.
    assert edited.data["frequency"] == "monthly"
    assert edited.data["is_active"] is True

    # Cadence change re-anchors the next run from `starts_on`, not from
    # whatever date was sitting in the column.
    requartered = client.patch(
        f"/api/v1/finance/recurring/{rec_id}/",
        {"frequency": "monthly", "interval": 3},
        format="json",
    )
    assert requartered.status_code == 200, requartered.data
    assert requartered.data["interval"] == 3
    assert str(requartered.data["next_run_on"]) == "2026-01-01"


def test_recurring_edit_rejects_what_would_reinterpret_history(tenant_context):
    """Currency and type are not editable — every posted occurrence carries
    them, so a change would rewrite the books rather than correct the plan."""
    _, client = tenant_context
    acct = _account(client)
    cat = _category(client, "Streaming", "expense")
    rec = client.post(
        "/api/v1/finance/recurring/",
        {
            "txn_type": "expense",
            "financial_account_id": acct["id"],
            "category_id": cat["id"],
            "amount_minor": 1500,
            "currency": "USD",
            "frequency": "monthly",
            "starts_on": "2026-01-01",
        },
        format="json",
    ).data

    # Unknown/!editable keys are ignored by the serializer, so the schedule is
    # unchanged rather than silently re-denominated.
    resp = client.patch(
        f"/api/v1/finance/recurring/{rec['id']}/",
        {"currency": "KES", "txn_type": "income", "amount_minor": 1600},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["currency"] == "USD"
    assert resp.data["txn_type"] == "expense"
    assert resp.data["amount_minor"] == 1600

    # An amount below the minimum is refused rather than clamped.
    bad = client.patch(f"/api/v1/finance/recurring/{rec['id']}/", {"amount_minor": 0}, format="json")
    assert bad.status_code == 400


def test_the_csv_import_offers_a_template(tenant_context):
    """A format described only in prose is one people get wrong on the first
    try and then blame the importer for."""
    _, client = tenant_context

    resp = client.get("/api/v1/finance/transactions/import/")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv"
    assert "ledgerflow-import-template.csv" in resp["Content-Disposition"]

    body = resp.content.decode()
    header, *rows = [line for line in body.splitlines() if line]
    assert header == "date,amount,description,external_id"
    # Two examples, and the pair is the point: sign is direction, which is the
    # one rule about this format that cannot be guessed from the header.
    assert len(rows) == 2
    assert rows[0].split(",")[1].startswith("-"), "money out"
    assert not rows[1].split(",")[1].startswith("-"), "money in"


def test_the_template_columns_are_the_ones_the_importer_accepts(tenant_context):
    """The template and the parser must not drift; they share a module so that
    is structural, and this is the check that keeps it so."""
    from apps.finance.import_csv import _ALIASES, TEMPLATE_HEADER

    for column in TEMPLATE_HEADER:
        assert column in _ALIASES, f"{column} is not a column the importer knows"
    # Everything the importer *requires* has to be in the template.
    assert {"date", "amount", "description"} <= set(TEMPLATE_HEADER)
