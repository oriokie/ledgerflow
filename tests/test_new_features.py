"""Tests for bills, notifications, forecasting, CSV import, missed-recurring."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from apps.finance import bills as bills_service
from apps.finance import services as finance_services
from apps.finance.models import AccountType, BillStatus, CategoryKind
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


def _now():
    return datetime.now(UTC)


# ------------------------------------------------------------------- bills
def test_bill_due_soon_and_pay_records_expense():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        rent_cat = finance_services.create_category(name="Rent", kind=CategoryKind.EXPENSE, currency="USD")
        bill = bills_service.create_bill(
            name="Rent",
            amount_minor=150000,
            currency="USD",
            due_on=date.today() + timedelta(days=3),
            category=rent_cat,
        )
        upcoming = bills_service.upcoming_bills(within_days=7)
        assert any(ub.bill.id == bill.id for ub in upcoming)

        bill, txn = bills_service.mark_bill_paid(bill=bill, from_account=checking)
        assert bill.status == BillStatus.PAID
        assert txn is not None
        assert txn.amount_minor == -150000  # a real expense posted


def test_recurring_bill_spawns_next_on_payment():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        cat = finance_services.create_category(name="Utilities", kind=CategoryKind.EXPENSE, currency="USD")
        bill = bills_service.create_bill(
            name="Electric",
            amount_minor=8000,
            currency="USD",
            due_on=date(2026, 1, 15),
            category=cat,
            recurrence_frequency="monthly",
        )
        bills_service.mark_bill_paid(bill=bill, from_account=checking)
        # a new upcoming bill for the next month should now exist
        all_bills = list(bills_service.list_bills())
        upcoming = [b for b in all_bills if b.status == BillStatus.UPCOMING]
        assert len(upcoming) == 1
        assert upcoming[0].due_on == date(2026, 2, 15)


def test_mark_overdue():
    tid = uuid.uuid4()
    with tenant_scope(tid):
        bills_service.create_bill(
            name="Late", amount_minor=1000, currency="USD", due_on=date.today() - timedelta(days=5)
        )
        count = bills_service.mark_overdue()
        assert count == 1
        assert bills_service.list_bills(status=BillStatus.OVERDUE)


# ------------------------------------------------------------- notifications
def test_budget_alert_raised_when_over_threshold():
    from apps.budgeting import services as budget_services
    from apps.notifications import services as notif_services
    from apps.notifications.models import NotificationType

    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        groceries = finance_services.create_category(
            name="Groceries", kind=CategoryKind.EXPENSE, currency="USD"
        )
        budget = budget_services.create_budget(
            name="Monthly", currency="USD", starts_on=date.today().replace(day=1)
        )
        budget_services.add_budget_line(budget=budget, category=groceries, limit_minor=10000)
        # spend past the limit
        finance_services.record_expense(
            financial_account=checking, category=groceries, amount_minor=12000, occurred_at=_now()
        )
        raised = notif_services.evaluate_budget_alerts()
        assert any(n.type == NotificationType.BUDGET_EXCEEDED for n in raised)


def test_notification_dedupe():
    from apps.notifications import services as notif_services
    from apps.notifications.models import NotificationType

    tid = uuid.uuid4()
    with tenant_scope(tid):
        n1 = notif_services.raise_notification(
            type=NotificationType.LOW_BALANCE,
            title="Low balance",
            dedupe_key="low:acct1:202601",
        )
        n2 = notif_services.raise_notification(
            type=NotificationType.LOW_BALANCE,
            title="Low balance (updated)",
            dedupe_key="low:acct1:202601",
        )
        # same dedupe key -> same row, refreshed, not a duplicate
        assert n1.id == n2.id
        assert n2.title == "Low balance (updated)"


# ---------------------------------------------------------------- forecast
def test_forecast_returns_points():
    from apps.intelligence import services as intel_services

    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        groceries = finance_services.create_category(
            name="Groceries", kind=CategoryKind.EXPENSE, currency="USD"
        )
        # a few months of history
        for m in range(1, 4):
            finance_services.record_expense(
                financial_account=checking,
                category=groceries,
                amount_minor=10000 * m,
                occurred_at=_now() - timedelta(days=30 * m),
            )
        result = intel_services.forecast(months_history=6, periods_ahead=2)
        assert len(result.points) == 2
        assert result.provenance.provider  # provenance is populated


# ------------------------------------------------------------------ import
def test_csv_import_is_idempotent():
    from apps.finance import import_csv

    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        csv_text = (
            "date,amount,description,external_id\n"
            "2026-01-05,-42.50,Coffee shop,txn-1\n"
            "2026-01-06,-18.00,Lunch,txn-2\n"
            "2026-01-07,2500.00,Paycheck,txn-3\n"
        )
        r1 = import_csv.import_transactions_csv(financial_account=checking, file_content=csv_text)
        assert r1.imported == 3
        assert r1.errors == []
        # re-import the same file: everything is a duplicate, nothing new
        r2 = import_csv.import_transactions_csv(financial_account=checking, file_content=csv_text)
        assert r2.imported == 0
        assert r2.skipped_duplicate == 3


def test_a_row_failing_in_the_database_does_not_abort_the_csv_import():
    """Regression: the per-row `except` sat inside the function's atomic block
    with no savepoint.

    The failure has to come from a statement *outside* the posting services —
    they are each `@transaction.atomic`, so an error inside one rolls back to
    its own savepoint and leaves the transaction healthy. The exposed statement
    is the `txn.save()` that stamps `external_id`, and a CSV is free to carry an
    id longer than the 128-character column. Without a savepoint that error
    marks the whole transaction broken, every later query raises
    TransactionManagementError, and the importer reports rows it never wrote.
    """
    from apps.finance import import_csv
    from apps.finance.models import Transaction

    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        csv_text = (
            "date,amount,description,external_id\n"
            f"2026-01-05,-42.50,Coffee shop,{'x' * 200}\n"
            "2026-01-06,-18.00,Lunch,good-1\n"
            "2026-01-07,2500.00,Paycheck,good-2\n"
        )
        result = import_csv.import_transactions_csv(financial_account=checking, file_content=csv_text)

        assert len(result.errors) == 1, result.errors
        assert result.imported == 2, "the rows after the failure must still land"
        assert Transaction.objects.filter(financial_account=checking).count() == 2


def test_csv_import_reports_bad_rows():
    from apps.finance import import_csv

    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        csv_text = "date,amount,description\n" "2026-01-05,-42.50,Good row\n" "not-a-date,-10.00,Bad date\n"
        result = import_csv.import_transactions_csv(financial_account=checking, file_content=csv_text)
        assert result.imported == 1
        assert len(result.errors) == 1


# --------------------------------------------------------- missed recurring
def test_detect_missed_recurring():
    from apps.finance import recurring as recurring_service
    from apps.finance.models import Frequency
    from apps.intelligence import services as intel_services

    tid = uuid.uuid4()
    with tenant_scope(tid):
        checking = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        cat = finance_services.create_category(
            name="Subscriptions", kind=CategoryKind.EXPENSE, currency="USD"
        )
        rec = recurring_service.create_recurring_transaction(
            financial_account=checking,
            category=cat,
            txn_type="expense",
            amount_minor=999,
            currency="USD",
            frequency=Frequency.MONTHLY,
            starts_on=date.today() - timedelta(days=40),
        )
        # next_run_on is well in the past and no matching txn exists
        missed = intel_services.detect_missed_recurring(grace_days=3)
        assert any(m["recurring_id"] == str(rec.id) for m in missed)


@pytest.mark.django_db(transaction=True)
def test_alert_sweep_task_marks_overdue_and_notifies():
    """The daily sweep marks bills overdue and raises alerts, under the tenant's
    own RLS binding (transaction=True so the task's atomic block behaves like a
    real worker's)."""
    from apps.notifications.models import Notification
    from apps.notifications.tasks import run_alert_sweep_for_tenant
    from tests.factories import MembershipFactory

    membership = MembershipFactory()
    tenant_id = membership.tenant_id
    with tenant_scope(tenant_id, actor_id=membership.user_id):
        bills_service.create_bill(
            name="Overdue thing",
            amount_minor=5000,
            currency="USD",
            due_on=date.today() - timedelta(days=2),
        )
    # eager task execution
    run_alert_sweep_for_tenant(str(tenant_id))
    with tenant_scope(tenant_id):
        assert Notification.objects.filter(type="bill_overdue").exists()
