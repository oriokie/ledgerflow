"""Transfers must never read as income or spending in the reporting platform.

`record_transfer` documents the contract plainly: "Reports exclude anything
with a `transfer_group`, so a transfer never inflates spending or income."
The finance selectors honour it via `_NOT_TRANSFER`. The reports module
aggregates over `Transaction` directly and did not, so every movement between
a user's own accounts was counted twice — once as income on the leg coming in,
once as spending on the leg going out.

This matters more now that funding a savings goal posts a real transfer: a
household diligently moving money into savings would have watched its reported
spending climb by exactly the amount it saved.
"""

from __future__ import annotations

import uuid

import pytest

from apps.analytics.filters import ReportFilters
from apps.analytics.reports import run_report
from apps.finance import services as finance_services
from apps.finance.models import AccountType
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def _two_accounts():
    checking = finance_services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency="USD"
    )
    savings = finance_services.create_financial_account(
        name="Savings", account_type=AccountType.SAVINGS, currency="USD"
    )
    finance_services.set_opening_balance(financial_account=checking, amount_minor=1000_00)
    return checking, savings


def test_a_transfer_is_not_spending():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking, savings = _two_accounts()
        from django.utils import timezone

        finance_services.record_transfer(
            from_account=checking,
            to_account=savings,
            amount_minor=300_00,
            occurred_at=timezone.now(),
        )

        result = run_report("cash_flow", ReportFilters(currency="USD"))
        outflow = sum(point.get("outflow_minor", 0) for point in result.series)
        inflow = sum(point.get("inflow_minor", 0) for point in result.series)

        # Moving your own money between your own accounts is neither.
        assert outflow == 0, f"transfer counted as {outflow} of spending"
        assert inflow == 0, f"transfer counted as {inflow} of income"


def test_a_transfer_does_not_appear_in_category_spending():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking, savings = _two_accounts()
        from django.utils import timezone

        finance_services.record_transfer(
            from_account=checking,
            to_account=savings,
            amount_minor=250_00,
            occurred_at=timezone.now(),
        )

        result = run_report("category_analytics", ReportFilters(currency="USD"))
        assert result.totals.get("total_minor", 0) == 0


def test_real_spending_still_counts():
    """The exclusion must be surgical — it would be easy to filter out everything."""
    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking, savings = _two_accounts()
        from django.utils import timezone

        groceries = finance_services.create_category(name="Groceries", kind="expense", currency="USD")
        finance_services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=80_00,
            occurred_at=timezone.now(),
            memo="Groceries",
        )
        finance_services.record_transfer(
            from_account=checking,
            to_account=savings,
            amount_minor=300_00,
            occurred_at=timezone.now(),
        )

        result = run_report("cash_flow", ReportFilters(currency="USD"))
        outflow = sum(point.get("outflow_minor", 0) for point in result.series)
        assert outflow == 80_00
