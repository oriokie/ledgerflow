"""Core financial-engine tests — the invariants a money product must never
get wrong. Every posting is checked against BOTH the domain Transaction and
the immutable double-entry ledger it produced."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.finance import selectors, services
from apps.finance.models import AccountType, CategoryKind, Transaction, TransactionStatus
from apps.ledger.models import Account, AccountKind
from apps.ledger.selectors import recompute_balance_minor
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


def _now():
    return datetime.now(UTC)


def _seed(currency="USD"):
    """A checking account, a credit card, and income/expense categories."""
    checking = services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency=currency
    )
    card = services.create_financial_account(
        name="Visa", account_type=AccountType.CREDIT_CARD, currency=currency
    )
    savings = services.create_financial_account(
        name="Savings", account_type=AccountType.SAVINGS, currency=currency
    )
    groceries = services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency=currency)
    salary = services.create_category(name="Salary", kind=CategoryKind.INCOME, currency=currency)
    return checking, card, savings, groceries, salary


# --------------------------------------------------------------- provisioning
def test_financial_account_provisions_ledger_account(tenant_id):
    with tenant_scope(tenant_id):
        checking = services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        card = services.create_financial_account(
            name="Visa", account_type=AccountType.CREDIT_CARD, currency="USD"
        )
        assert checking.ledger_account.kind == AccountKind.ASSET
        assert card.ledger_account.kind == AccountKind.LIABILITY
        assert selectors.account_current_balance_minor(checking) == 0


def test_category_provisions_contra_account(tenant_id):
    with tenant_scope(tenant_id):
        groceries = services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
        salary = services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
        assert groceries.ledger_account.kind == AccountKind.EXPENSE
        assert salary.ledger_account.kind == AccountKind.INCOME


# --------------------------------------------------------------- expense/income
def test_expense_is_balanced_double_entry(tenant_id):
    with tenant_scope(tenant_id):
        checking, _card, _savings, groceries, _salary = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        assert txn.amount_minor == -5000  # signed: money out
        assert txn.status == TransactionStatus.POSTED
        # the ledger entry it produced is balanced
        lines = list(txn.journal_entry.lines.all())
        assert sum(line.amount_minor for line in lines if line.direction == "debit") == 5000
        assert sum(line.amount_minor for line in lines if line.direction == "credit") == 5000
        # asset down, expense up
        assert selectors.account_current_balance_minor(checking) == -5000
        checking.ledger_account.refresh_from_db()
        assert recompute_balance_minor(checking.ledger_account) == -5000


def test_income_increases_account_and_is_positive(tenant_id):
    with tenant_scope(tenant_id):
        checking, _card, _savings, _groceries, salary = _seed()
        txn = services.record_income(
            financial_account=checking, category=salary, amount_minor=300000, occurred_at=_now()
        )
        assert txn.amount_minor == 300000
        assert selectors.account_current_balance_minor(checking) == 300000


def test_credit_card_expense_increases_debt_and_lowers_net_worth(tenant_id):
    with tenant_scope(tenant_id):
        _checking, card, _savings, groceries, _salary = _seed()
        services.record_expense(
            financial_account=card, category=groceries, amount_minor=8000, occurred_at=_now()
        )
        # liability ledger balance = amount owed = +8000
        assert selectors.account_current_balance_minor(card) == 8000
        nw = {n.currency: n for n in selectors.net_worth()}["USD"]
        assert nw.liabilities_minor == 8000
        assert nw.net_minor == -8000  # you owe money, net worth is negative


def test_expense_requires_expense_category(tenant_id):
    with tenant_scope(tenant_id):
        checking, _card, _savings, _groceries, salary = _seed()
        with pytest.raises(services.CategoryKindError):
            services.record_expense(
                financial_account=checking, category=salary, amount_minor=100, occurred_at=_now()
            )


def test_expense_posts_in_account_currency_across_categories(tenant_id):
    """A category is currency-agnostic: posting to a USD account uses USD even
    if the category's primary ledger account was created in another currency.
    The engine provisions a per-currency sibling rather than rejecting."""
    with tenant_scope(tenant_id):
        usd_checking = services.create_financial_account(
            name="US Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        eur_groceries = services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="EUR")
        txn = services.record_expense(
            financial_account=usd_checking, category=eur_groceries, amount_minor=100, occurred_at=_now()
        )
        assert txn.currency == "USD"
        assert txn.amount_minor == -100


def test_idempotent_posting_does_not_double_apply(tenant_id):
    with tenant_scope(tenant_id):
        checking, _card, _savings, groceries, _salary = _seed()
        services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=5000,
            occurred_at=_now(),
            idempotency_key="dup-key",
        )
        services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=5000,
            occurred_at=_now(),
            idempotency_key="dup-key",
        )
        # balance moved once, not twice
        assert selectors.account_current_balance_minor(checking) == -5000


# --------------------------------------------------------------- transfers
def test_transfer_is_not_income_or_expense_and_nets_to_zero(tenant_id):
    with tenant_scope(tenant_id):
        checking, _card, savings, _groceries, _salary = _seed()
        # fund checking first
        salary = services.create_category(name="Bonus", kind=CategoryKind.INCOME, currency="USD")
        services.record_income(
            financial_account=checking, category=salary, amount_minor=100000, occurred_at=_now()
        )

        out_txn, in_txn = services.record_transfer(
            from_account=checking, to_account=savings, amount_minor=40000, occurred_at=_now()
        )
        # two linked domain rows, one shared balanced entry
        assert out_txn.transfer_group == in_txn.transfer_group
        assert out_txn.journal_entry_id == in_txn.journal_entry_id
        assert out_txn.amount_minor == -40000 and in_txn.amount_minor == 40000

        assert selectors.account_current_balance_minor(checking) == 60000
        assert selectors.account_current_balance_minor(savings) == 40000

        # net worth unchanged by the move (still the 100000 that came in)
        nw = {n.currency: n for n in selectors.net_worth()}["USD"]
        assert nw.net_minor == 100000

        # transfers excluded from cash flow
        flow = {
            c.currency: c
            for c in selectors.cash_flow(start=_now() - timedelta(days=1), end=_now() + timedelta(days=1))
        }["USD"]
        assert flow.income_minor == 100000  # only the salary, NOT the transfer
        assert flow.expense_minor == 0


def test_transfer_same_account_rejected(tenant_id):
    with tenant_scope(tenant_id):
        checking, *_ = _seed()
        with pytest.raises(services.FinanceError):
            services.record_transfer(
                from_account=checking, to_account=checking, amount_minor=100, occurred_at=_now()
            )


# --------------------------------------------------------------- void
def test_void_reverses_balance_and_marks_void(tenant_id):
    with tenant_scope(tenant_id):
        checking, _card, _savings, groceries, _salary = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        assert selectors.account_current_balance_minor(checking) == -5000

        services.void_transaction(txn=txn)
        txn.refresh_from_db()
        assert txn.status == TransactionStatus.VOID
        assert selectors.account_current_balance_minor(checking) == 0  # reversed


def test_void_transfer_voids_both_halves(tenant_id):
    with tenant_scope(tenant_id):
        checking, _card, savings, _groceries, _salary = _seed()
        income = services.create_category(name="In", kind=CategoryKind.INCOME, currency="USD")
        services.record_income(
            financial_account=checking, category=income, amount_minor=50000, occurred_at=_now()
        )
        out_txn, in_txn = services.record_transfer(
            from_account=checking, to_account=savings, amount_minor=20000, occurred_at=_now()
        )

        services.void_transaction(txn=out_txn)
        out_txn.refresh_from_db()
        in_txn.refresh_from_db()
        assert out_txn.status == TransactionStatus.VOID
        assert in_txn.status == TransactionStatus.VOID
        assert selectors.account_current_balance_minor(checking) == 50000  # back to pre-transfer
        assert selectors.account_current_balance_minor(savings) == 0


# --------------------------------------------------------------- statements
def test_account_statement_running_balance_asset(tenant_id):
    with tenant_scope(tenant_id):
        checking, _card, _savings, groceries, salary = _seed()
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        services.record_income(
            financial_account=checking, category=salary, amount_minor=100000, occurred_at=t0
        )
        services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=3000,
            occurred_at=t0 + timedelta(days=1),
        )
        opening, rows = selectors.account_statement(
            financial_account=checking,
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 2, 1, tzinfo=UTC),
        )
        assert opening == 0
        running_balances = [running for _txn, running in rows]
        assert running_balances == [100000, 97000]  # after income, then after groceries


def test_account_statement_liability_shows_debt_growing(tenant_id):
    with tenant_scope(tenant_id):
        _checking, card, _savings, groceries, _salary = _seed()
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        services.record_expense(financial_account=card, category=groceries, amount_minor=5000, occurred_at=t0)
        services.record_expense(
            financial_account=card, category=groceries, amount_minor=2000, occurred_at=t0 + timedelta(days=1)
        )
        _opening, rows = selectors.account_statement(
            financial_account=card,
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 2, 1, tzinfo=UTC),
        )
        running = [r for _t, r in rows]
        assert running == [5000, 7000]  # debt owed grows with each purchase


def test_category_breakdown(tenant_id):
    with tenant_scope(tenant_id):
        checking, _card, _savings, groceries, _salary = _seed()
        dining = services.create_category(name="Dining", kind=CategoryKind.EXPENSE, currency="USD")
        t = _now()
        services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=t
        )
        services.record_expense(
            financial_account=checking, category=groceries, amount_minor=3000, occurred_at=t
        )
        services.record_expense(financial_account=checking, category=dining, amount_minor=6000, occurred_at=t)
        breakdown = selectors.category_breakdown(
            start=t - timedelta(days=1), end=t + timedelta(days=1), expense=True
        )
        # biggest first: groceries 8000, dining 6000
        assert [(c.category_name, c.amount_minor) for c in breakdown] == [
            ("Groceries", 8000),
            ("Dining", 6000),
        ]


# --------------------------------------------------------------- isolation
def test_transactions_are_tenant_isolated():
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with tenant_scope(tenant_a):
        checking, _card, _savings, groceries, _salary = _seed()
        services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
    with tenant_scope(tenant_b):
        # RLS: tenant B sees none of tenant A's accounts or balances
        assert list(Account.objects.all()) == []
        assert selectors.net_worth() == []


# =============================================================================
# Replay safety: post_journal_entry dedupes the ledger entry, but each of
# record_expense/record_income/record_transfer must equally avoid creating a
# *second* Transaction row pointing at that same (replayed) entry — nothing at
# the database level prevents it, since Transaction.journal_entry is a plain
# ForeignKey rather than a OneToOneField.
# =============================================================================
def test_replaying_record_expense_does_not_create_a_second_transaction():
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        account = services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=500_000,
        )
        category = services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
        key = "replay-key-expense"
        first = services.record_expense(
            financial_account=account,
            category=category,
            amount_minor=1_000,
            occurred_at=timezone.now(),
            idempotency_key=key,
        )
        second = services.record_expense(
            financial_account=account,
            category=category,
            amount_minor=1_000,
            occurred_at=timezone.now(),
            idempotency_key=key,
        )
        assert first.id == second.id
        assert Transaction.objects.filter(journal_entry=first.journal_entry).count() == 1


def test_replaying_record_income_does_not_create_a_second_transaction():
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        account = services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        category = services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
        key = "replay-key-income"
        first = services.record_income(
            financial_account=account,
            category=category,
            amount_minor=50_000,
            occurred_at=timezone.now(),
            idempotency_key=key,
        )
        second = services.record_income(
            financial_account=account,
            category=category,
            amount_minor=50_000,
            occurred_at=timezone.now(),
            idempotency_key=key,
        )
        assert first.id == second.id
        assert Transaction.objects.filter(journal_entry=first.journal_entry).count() == 1


def test_replaying_record_transfer_does_not_create_extra_legs():
    """A transfer posts two Transaction rows by design (one per account) — a
    replay must still resolve to exactly those two, not four."""
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        checking = services.create_financial_account(
            name="Checking",
            account_type=AccountType.CHECKING,
            currency="USD",
            opening_balance_minor=500_000,
        )
        savings = services.create_financial_account(
            name="Savings", account_type=AccountType.SAVINGS, currency="USD"
        )
        key = "replay-key-transfer"
        out1, in1 = services.record_transfer(
            from_account=checking,
            to_account=savings,
            amount_minor=20_000,
            occurred_at=timezone.now(),
            idempotency_key=key,
        )
        out2, in2 = services.record_transfer(
            from_account=checking,
            to_account=savings,
            amount_minor=20_000,
            occurred_at=timezone.now(),
            idempotency_key=key,
        )
        assert out1.id == out2.id
        assert in1.id == in2.id
        assert Transaction.objects.filter(journal_entry=out1.journal_entry).count() == 2


def test_a_fresh_idempotency_key_still_posts_normally():
    """The guard must be a no-op on the common, non-replay path."""
    tenant = uuid.uuid4()
    with tenant_scope(tenant):
        account = services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        category = services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
        services.record_expense(
            financial_account=account,
            category=category,
            amount_minor=1_000,
            occurred_at=timezone.now(),
            idempotency_key="key-1",
        )
        services.record_expense(
            financial_account=account,
            category=category,
            amount_minor=1_000,
            occurred_at=timezone.now(),
            idempotency_key="key-2",
        )
        assert Transaction.objects.count() == 2
