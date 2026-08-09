"""`services.reclassify_as_transfer`: fixing a statement-import row that was
actually a transfer between two of the household's own accounts, not real
income or spending."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from apps.finance import selectors, services
from apps.finance.models import AccountType, CategoryKind, TransactionStatus
from apps.finance.reconciliation import set_reconciled
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


def _now():
    return datetime.now(UTC)


def _seed(currency="USD"):
    checking = services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency=currency
    )
    savings = services.create_financial_account(
        name="Savings", account_type=AccountType.SAVINGS, currency=currency
    )
    groceries = services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency=currency)
    salary = services.create_category(name="Salary", kind=CategoryKind.INCOME, currency=currency)
    return checking, savings, groceries, salary


def test_reclassify_income_leg_as_transfer(tenant_id):
    with tenant_scope(tenant_id):
        checking, savings, _groceries, salary = _seed()
        # Posted as if it were plain income into savings...
        credit = services.record_income(
            financial_account=savings, category=salary, amount_minor=40000, occurred_at=_now()
        )

        out_txn, in_txn = services.reclassify_as_transfer(txn=credit, counter_account=checking)

        credit.refresh_from_db()
        assert credit.status == TransactionStatus.VOID
        assert out_txn.financial_account_id == checking.id
        assert in_txn.financial_account_id == savings.id
        assert out_txn.transfer_group == in_txn.transfer_group
        assert selectors.account_current_balance_minor(savings) == 40000
        assert selectors.account_current_balance_minor(checking) == -40000

        flow = {
            c.currency: c
            for c in selectors.cash_flow(start=_now() - timedelta(days=1), end=_now() + timedelta(days=1))
        }.get("USD")
        assert flow is None or flow.income_minor == 0


def test_reclassify_expense_leg_as_transfer(tenant_id):
    with tenant_scope(tenant_id):
        checking, savings, groceries, _salary = _seed()
        # Posted as if it were a plain expense out of checking...
        debit = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=15000, occurred_at=_now()
        )

        out_txn, in_txn = services.reclassify_as_transfer(txn=debit, counter_account=savings)

        debit.refresh_from_db()
        assert debit.status == TransactionStatus.VOID
        assert out_txn.financial_account_id == checking.id
        assert in_txn.financial_account_id == savings.id
        assert selectors.account_current_balance_minor(checking) == -15000
        assert selectors.account_current_balance_minor(savings) == 15000


def test_reclassify_rejects_already_transfer(tenant_id):
    with tenant_scope(tenant_id):
        checking, savings, _groceries, salary = _seed()
        services.record_income(
            financial_account=checking, category=salary, amount_minor=100000, occurred_at=_now()
        )
        out_txn, _in_txn = services.record_transfer(
            from_account=checking, to_account=savings, amount_minor=20000, occurred_at=_now()
        )
        with pytest.raises(services.FinanceError, match="already a transfer"):
            services.reclassify_as_transfer(txn=out_txn, counter_account=checking)


def test_reclassify_rejects_void(tenant_id):
    with tenant_scope(tenant_id):
        checking, savings, groceries, _salary = _seed()
        debit = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        services.void_transaction(txn=debit)
        debit.refresh_from_db()
        with pytest.raises(services.FinanceError, match="voided"):
            services.reclassify_as_transfer(txn=debit, counter_account=savings)


def test_reclassify_rejects_split_part(tenant_id):
    with tenant_scope(tenant_id):
        checking, savings, groceries, _salary = _seed()
        household = services.create_category(name="Household", kind=CategoryKind.EXPENSE, currency="USD")
        debit = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=20000, occurred_at=_now()
        )
        parts = services.split_transaction(
            txn=debit,
            parts=[
                services.SplitPart(category=groceries, amount_minor=15000),
                services.SplitPart(category=household, amount_minor=5000),
            ],
        )
        with pytest.raises(services.FinanceError, match="split"):
            services.reclassify_as_transfer(txn=parts[0], counter_account=savings)


def test_reclassify_rejects_reconciled(tenant_id):
    with tenant_scope(tenant_id):
        checking, savings, groceries, _salary = _seed()
        debit = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        set_reconciled(transactions=[debit], reconciled=True)
        debit.refresh_from_db()
        with pytest.raises(services.FinanceError, match="reconcil"):
            services.reclassify_as_transfer(txn=debit, counter_account=savings)


def test_reclassify_cross_currency_raises_currency_mismatch(tenant_id):
    with tenant_scope(tenant_id):
        checking, _savings, _groceries, salary = _seed(currency="USD")
        eur_account = services.create_financial_account(
            name="EUR Checking", account_type=AccountType.CHECKING, currency="EUR"
        )
        credit = services.record_income(
            financial_account=checking, category=salary, amount_minor=10000, occurred_at=_now()
        )
        with pytest.raises(services.CurrencyMismatchError):
            services.reclassify_as_transfer(txn=credit, counter_account=eur_account)
