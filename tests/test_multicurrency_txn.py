"""#1 regression: posting to an account whose currency differs from the base
(and thus the seeded categories) must succeed, not raise a cross-currency error."""

from __future__ import annotations

import contextlib
import pytest
from django.db import transaction as db_tx
from django.utils import timezone

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from apps.finance import services as fin

pytestmark = pytest.mark.django_db


@contextlib.contextmanager
def _ctx(m):
    with db_tx.atomic(), use_tenant(m.tenant_id, m.user_id):
        bind_db_tenant(m.tenant_id)
        yield


def test_expense_in_non_base_currency_account(tenant_context):
    m, _ = tenant_context
    with _ctx(m):
        # base categories are USD (seeded); account is EUR
        cat = fin.create_category(name="Groceries", kind="expense", currency="USD")
        eur = fin.create_financial_account(name="EU Checking", account_type="checking", currency="EUR")
        txn = fin.record_expense(
            financial_account=eur, category=cat, amount_minor=5000,
            occurred_at=timezone.now(), memo="EUR groceries",
        )
        assert txn.currency == "EUR"
        assert txn.amount_minor == -5000
        # And a USD account against the same category still works.
        usd = fin.create_financial_account(name="US Checking", account_type="checking", currency="USD")
        txn2 = fin.record_expense(
            financial_account=usd, category=cat, amount_minor=2500,
            occurred_at=timezone.now(), memo="USD groceries",
        )
        assert txn2.currency == "USD"
