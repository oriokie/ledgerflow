"""Statement reconciliation.

`TransactionStatus.RECONCILED` shipped in the first migration, was read by two
selectors, and was written by nothing — the state was unreachable. These tests
cover the transition that was missing, and the rules that keep the difference
figure honest.
"""

from __future__ import annotations

import itertools
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.finance.models import Transaction, TransactionStatus
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


def _setup(balance=1_000_000):
    """A funded account, because that is what a real one is.

    A workspace blocks manual overdrafts by default, so an account with nothing
    in it cannot record the expenses these tests reconcile. The figures asserted
    below are sums of *cleared transactions*, not balances, so the opening
    amount does not appear in any of them.
    """
    membership = MembershipFactory()
    client = _bearer_client(membership.user, tenant_id=membership.tenant_id)
    account = client.post(
        "/api/v1/finance/accounts/",
        {
            "name": "Current",
            "account_type": "checking",
            "currency": "USD",
            **({"opening_balance_minor": balance} if balance else {}),
        },
        format="json",
    ).data
    # Test tenants are built by the factory rather than `create_workspace`, so
    # they skip default-category seeding — make one explicitly.
    category = client.post(
        "/api/v1/finance/categories/", {"name": "Living", "kind": "expense", "currency": "USD"}, format="json"
    )
    assert category.status_code in (200, 201), category.data
    return membership, client, {**account, "_category_id": category.data["id"]}


_seq = itertools.count()


def _spend(client, account, amount, memo="Coffee"):
    """Expenses are posted with a signed negative amount by the service, so the
    reconciliation sums below are negative — that is the ledger's convention,
    not a quirk of these tests."""
    r = client.post(
        "/api/v1/finance/transactions/",
        {
            "type": "expense",
            "financial_account_id": account["id"],
            "category_id": account["_category_id"],
            "amount_minor": amount,
            # Spread occurrence so "oldest first" has a stable order to assert.
            "occurred_at": (timezone.now() + timedelta(seconds=next(_seq))).isoformat(),
            "memo": memo,
        },
        format="json",
    )
    assert r.status_code in (200, 201), r.data
    return r.data


# ------------------------------------------------------------------ the gap
def test_a_transaction_can_now_be_reconciled():
    """The transition that did not exist."""
    _, client, account = _setup()
    txn = _spend(client, account, 500)

    response = client.post(
        "/api/v1/finance/transactions/reconcile/",
        {"transaction_ids": [txn["id"]], "reconciled": True},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["updated"] == 1
    assert Transaction.unscoped.get(id=txn["id"]).status == TransactionStatus.RECONCILED


def test_reconciling_stamps_when_it_happened():
    _, client, account = _setup()
    txn = _spend(client, account, 500)
    client.post(
        "/api/v1/finance/transactions/reconcile/",
        {"transaction_ids": [txn["id"]]},
        format="json",
    )
    assert Transaction.unscoped.get(id=txn["id"]).reconciled_at is not None


def test_unreconciling_is_a_normal_correction():
    """People mis-tick; undoing must not be an administrative exception."""
    _, client, account = _setup()
    txn = _spend(client, account, 500)
    client.post("/api/v1/finance/transactions/reconcile/", {"transaction_ids": [txn["id"]]}, format="json")

    response = client.post(
        "/api/v1/finance/transactions/reconcile/",
        {"transaction_ids": [txn["id"]], "reconciled": False},
        format="json",
    )
    assert response.status_code == 200
    row = Transaction.unscoped.get(id=txn["id"])
    assert row.status == TransactionStatus.POSTED
    assert row.reconciled_at is None


def test_a_whole_session_commits_in_one_request():
    """The natural unit is 'everything I just ticked'."""
    _, client, account = _setup()
    ids = [_spend(client, account, 100 * n, f"Item {n}")["id"] for n in range(1, 6)]

    response = client.post("/api/v1/finance/transactions/reconcile/", {"transaction_ids": ids}, format="json")
    assert response.data["updated"] == 5


# ------------------------------------------------------------------- rules
def test_a_voided_transaction_cannot_be_reconciled():
    """A void has no counterpart on any statement, so allowing it would let the
    difference be forced to zero with a row representing nothing."""
    _, client, account = _setup()
    txn = _spend(client, account, 500)
    client.post(f"/api/v1/finance/transactions/{txn['id']}/void/", {}, format="json")

    response = client.post(
        "/api/v1/finance/transactions/reconcile/", {"transaction_ids": [txn["id"]]}, format="json"
    )
    assert response.status_code == 422
    assert "statement" in response.data["detail"]


def test_an_unknown_transaction_is_a_404_not_a_partial_commit():
    import uuid

    _, client, account = _setup()
    txn = _spend(client, account, 500)
    response = client.post(
        "/api/v1/finance/transactions/reconcile/",
        {"transaction_ids": [txn["id"], str(uuid.uuid4())]},
        format="json",
    )
    assert response.status_code == 404
    # The valid row must not have been marked on the way to failing.
    assert Transaction.unscoped.get(id=txn["id"]).status == TransactionStatus.POSTED


def test_another_tenants_transaction_cannot_be_reconciled():
    _, client_a, account_a = _setup()
    txn = _spend(client_a, account_a, 500)
    _, client_b, _ = _setup()

    response = client_b.post(
        "/api/v1/finance/transactions/reconcile/", {"transaction_ids": [txn["id"]]}, format="json"
    )
    assert response.status_code == 404


# ----------------------------------------------------------------- summary
def test_the_difference_is_what_the_user_drives_to_zero():
    _, client, account = _setup()
    a = _spend(client, account, 1000, "Rent")
    _spend(client, account, 250, "Not yet cleared")
    client.post("/api/v1/finance/transactions/reconcile/", {"transaction_ids": [a["id"]]}, format="json")

    body = client.get(
        f"/api/v1/finance/accounts/{account['id']}/reconciliation/",
        {"statement_balance_minor": -1000},
    ).data

    assert body["reconciled_minor"] == -1000
    assert body["uncleared_minor"] == -250
    assert body["difference_minor"] == 0
    assert body["is_balanced"] is True


def test_a_discrepancy_shows_as_a_nonzero_difference():
    _, client, account = _setup()
    txn = _spend(client, account, 1000)
    client.post("/api/v1/finance/transactions/reconcile/", {"transaction_ids": [txn["id"]]}, format="json")

    body = client.get(
        f"/api/v1/finance/accounts/{account['id']}/reconciliation/",
        {"statement_balance_minor": -1200},
    ).data
    assert body["difference_minor"] == -200
    assert body["is_balanced"] is False


def test_the_summary_works_without_a_statement_balance():
    """Reconciled vs uncleared is useful on its own."""
    _, client, account = _setup()
    _spend(client, account, 300)
    body = client.get(f"/api/v1/finance/accounts/{account['id']}/reconciliation/").data

    assert body["statement_balance_minor"] is None
    assert body["difference_minor"] is None
    assert body["uncleared_count"] == 1


def test_uncleared_rows_are_listed_oldest_first():
    """Reconciliation works forward from the last statement."""
    _, client, account = _setup()
    _spend(client, account, 100, "First")
    _spend(client, account, 200, "Second")
    body = client.get(f"/api/v1/finance/accounts/{account['id']}/reconciliation/").data
    memos = [row["memo"] for row in body["uncleared"]]
    assert memos == ["First", "Second"]


def test_a_bad_statement_balance_is_a_field_error():
    _, client, account = _setup()
    response = client.get(
        f"/api/v1/finance/accounts/{account['id']}/reconciliation/",
        {"statement_balance_minor": "twelve pounds"},
    )
    assert response.status_code == 400
    assert "statement_balance_minor" in response.data


def test_nothing_is_auto_reconciled():
    """Automation proposes; reconciliation *is* the disposing."""
    _, client, account = _setup()
    _spend(client, account, 500)
    body = client.get(f"/api/v1/finance/accounts/{account['id']}/reconciliation/").data
    assert body["reconciled_count"] == 0
    assert body["uncleared_count"] == 1
