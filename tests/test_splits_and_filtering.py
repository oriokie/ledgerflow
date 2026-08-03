"""Tests for transaction splitting and the new list-filtering surface."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from apps.finance import selectors, services
from apps.finance.models import AccountType, CategoryKind, TransactionStatus
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def _now():
    return datetime.now(UTC)


def _seed(currency="USD"):
    checking = services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency=currency
    )
    groceries = services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency=currency)
    household = services.create_category(name="Household", kind=CategoryKind.EXPENSE, currency=currency)
    salary = services.create_category(name="Salary", kind=CategoryKind.INCOME, currency=currency)
    return checking, groceries, household, salary


# --------------------------------------------------------------------- splits
def test_split_divides_expense_across_categories():
    tenant_id = uuid.uuid4()
    with tenant_scope(tenant_id):
        checking, groceries, household, _ = _seed()
        txn = services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=20000,
            occurred_at=_now(),
            memo="Target run",
        )
        parts = [
            services.SplitPart(category=groceries, amount_minor=15000, memo="food"),
            services.SplitPart(category=household, amount_minor=5000, memo="cleaning"),
        ]
        created = services.split_transaction(txn=txn, parts=parts)

        assert len(created) == 2
        assert {t.category_id for t in created} == {groceries.id, household.id}
        assert sum(t.amount_minor for t in created) == -20000
        # all parts share one split_group and one journal entry
        assert len({t.split_group for t in created}) == 1
        assert len({t.journal_entry_id for t in created}) == 1
        # original is voided
        txn.refresh_from_db()
        assert txn.status == TransactionStatus.VOID


def test_split_must_sum_to_original():
    tenant_id = uuid.uuid4()
    with tenant_scope(tenant_id):
        checking, groceries, household, _ = _seed()
        txn = services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=20000,
            occurred_at=_now(),
        )
        with pytest.raises(services.FinanceError):
            services.split_transaction(
                txn=txn,
                parts=[
                    services.SplitPart(category=groceries, amount_minor=10000),
                    services.SplitPart(category=household, amount_minor=5000),  # sums to 150, not 200
                ],
            )


def test_split_preserves_account_balance():
    tenant_id = uuid.uuid4()
    with tenant_scope(tenant_id):
        checking, groceries, household, _ = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=9000, occurred_at=_now()
        )
        before = selectors.account_current_balance_minor(checking)
        services.split_transaction(
            txn=txn,
            parts=[
                services.SplitPart(category=groceries, amount_minor=6000),
                services.SplitPart(category=household, amount_minor=3000),
            ],
        )
        after = selectors.account_current_balance_minor(checking)
        # net money movement unchanged by a split (void + re-post nets to same)
        assert before == after


def test_income_cannot_be_split():
    tenant_id = uuid.uuid4()
    with tenant_scope(tenant_id):
        checking, groceries, household, salary = _seed()
        income = services.record_income(
            financial_account=checking, category=salary, amount_minor=50000, occurred_at=_now()
        )
        with pytest.raises(services.FinanceError):
            services.split_transaction(
                txn=income,
                parts=[
                    services.SplitPart(category=groceries, amount_minor=25000),
                    services.SplitPart(category=household, amount_minor=25000),
                ],
            )


# ------------------------------------------------------------------ filtering
def test_filter_by_type_and_amount_range():
    tenant_id = uuid.uuid4()
    with tenant_scope(tenant_id):
        checking, groceries, _, salary = _seed()
        services.record_expense(
            financial_account=checking, category=groceries, amount_minor=1000, occurred_at=_now()
        )
        services.record_expense(
            financial_account=checking, category=groceries, amount_minor=9000, occurred_at=_now()
        )
        services.record_income(
            financial_account=checking, category=salary, amount_minor=50000, occurred_at=_now()
        )

        expenses = list(selectors.list_transactions(filters=selectors.TransactionFilters(txn_type="expense")))
        assert len(expenses) == 2
        assert all(t.amount_minor < 0 for t in expenses)

        big = list(selectors.list_transactions(filters=selectors.TransactionFilters(min_amount_minor=5000)))
        # the 9000 expense and 50000 income, not the 1000 expense
        assert {abs(t.amount_minor) for t in big} == {9000, 50000}


def test_filter_by_search_matches_memo():
    tenant_id = uuid.uuid4()
    with tenant_scope(tenant_id):
        checking, groceries, _, _ = _seed()
        services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=1000,
            occurred_at=_now(),
            memo="Whole Foods weekly shop",
        )
        services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=2000,
            occurred_at=_now(),
            memo="Gas station",
        )
        hits = list(selectors.list_transactions(filters=selectors.TransactionFilters(search="whole foods")))
        assert len(hits) == 1
        assert hits[0].memo == "Whole Foods weekly shop"


def test_filter_by_date_range():
    tenant_id = uuid.uuid4()
    with tenant_scope(tenant_id):
        checking, groceries, _, _ = _seed()
        old = _now() - timedelta(days=40)
        recent = _now() - timedelta(days=2)
        services.record_expense(
            financial_account=checking, category=groceries, amount_minor=1000, occurred_at=old
        )
        services.record_expense(
            financial_account=checking, category=groceries, amount_minor=2000, occurred_at=recent
        )
        window = list(
            selectors.list_transactions(
                filters=selectors.TransactionFilters(start=_now() - timedelta(days=10))
            )
        )
        assert len(window) == 1
        assert window[0].amount_minor == -2000
