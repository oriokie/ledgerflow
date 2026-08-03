"""Ledger correctness tests — the invariants a finance product cannot get wrong.

Run with: pytest (pytest-django). These assume a configured test DB.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from apps.common.money import CurrencyMismatchError, Money
from apps.common.tenant_context import UnscopedAccessError
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


# ---- pure value object (no DB) -------------------------------------------
def test_money_rejects_float_and_cross_currency():
    with pytest.raises(TypeError):
        Money(10.5, "USD")  # floats are forbidden
    with pytest.raises(CurrencyMismatchError):
        Money(100, "USD") + Money(100, "EUR")
    # banker's rounding (ROUND_HALF_EVEN): .005 -> nearest even minor unit
    assert Money.from_decimal("10.005", "USD").amount_minor == 1000  # 10.00 (0 is even)
    assert Money.from_decimal("10.015", "USD").amount_minor == 1002  # 10.02 (2 is even)


# ---- fixtures -------------------------------------------------------------
@pytest.fixture
def tenant_id():
    return uuid.uuid4()


def _seed_accounts(services, models):
    checking = services.create_account(name="Checking", kind="asset", currency="USD")
    groceries = services.create_account(name="Groceries", kind="expense", currency="USD")
    return checking, groceries


# ---- structural isolation -------------------------------------------------
def test_unscoped_query_is_refused():
    from apps.ledger.models import Account

    with pytest.raises(UnscopedAccessError):
        list(Account.objects.all())  # no tenant in context => hard fail


# ---- double entry ---------------------------------------------------------
def test_balanced_posting_moves_money_correctly(tenant_id):
    from apps.ledger import selectors, services
    from apps.ledger.models import Account

    with tenant_scope(tenant_id):
        checking, groceries = _seed_accounts(services, None)
        services.post_journal_entry(
            occurred_at=datetime.now(UTC),
            idempotency_key="k1",
            lines=[
                services.LineInput(str(groceries.id), "debit", 5000),  # expense up
                services.LineInput(str(checking.id), "credit", 5000),  # asset down
            ],
        )
        checking.refresh_from_db()
        groceries.refresh_from_db()
        assert selectors.account_balance(Account.objects.get(id=checking.id)).amount_minor == -5000
        assert selectors.account_balance(Account.objects.get(id=groceries.id)).amount_minor == 5000
        # materialized balance must equal recomputation from immutable lines
        assert selectors.recompute_balance_minor(checking) == -5000


def test_unbalanced_posting_is_rejected(tenant_id):
    from apps.ledger import services
    from apps.ledger.services import UnbalancedEntryError

    with tenant_scope(tenant_id):
        checking, groceries = _seed_accounts(services, None)
        with pytest.raises(UnbalancedEntryError):
            services.post_journal_entry(
                occurred_at=datetime.now(UTC),
                idempotency_key="k2",
                lines=[
                    services.LineInput(str(groceries.id), "debit", 5000),
                    services.LineInput(str(checking.id), "credit", 4000),  # unbalanced
                ],
            )


def test_idempotent_replay_does_not_double_post(tenant_id):
    from apps.ledger import services
    from apps.ledger.models import JournalEntry

    with tenant_scope(tenant_id):
        checking, groceries = _seed_accounts(services, None)
        lines = [
            services.LineInput(str(groceries.id), "debit", 100),
            services.LineInput(str(checking.id), "credit", 100),
        ]
        e1 = services.post_journal_entry(occurred_at=datetime.now(UTC), idempotency_key="same", lines=lines)
        e2 = services.post_journal_entry(occurred_at=datetime.now(UTC), idempotency_key="same", lines=lines)
        assert e1.id == e2.id
        assert JournalEntry.objects.count() == 1


def test_reversal_zeroes_the_effect(tenant_id):
    from apps.ledger import selectors, services
    from apps.ledger.models import Account

    with tenant_scope(tenant_id):
        checking, groceries = _seed_accounts(services, None)
        entry = services.post_journal_entry(
            occurred_at=datetime.now(UTC),
            idempotency_key="orig",
            lines=[
                services.LineInput(str(groceries.id), "debit", 2500),
                services.LineInput(str(checking.id), "credit", 2500),
            ],
        )
        services.reverse_journal_entry(entry=entry, idempotency_key="rev")
        assert selectors.account_balance(Account.objects.get(id=checking.id)).amount_minor == 0
