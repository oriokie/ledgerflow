"""Excel (.xlsx) bulk import for Bills and Recurring — apps/finance/import_xlsx.py.

Not the transaction/statement importer (that stays CSV-only); this is for a
human filling in a spreadsheet by hand, hence name-based payee/category/
account resolution and major-unit amounts.
"""

from __future__ import annotations

import io
import uuid

import openpyxl
import pytest

from apps.finance import import_xlsx, services
from apps.finance.models import AccountType, Bill, CategoryKind, RecurringTransaction
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


def _workbook(header, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# =============================================================================
# Bills — service layer
# =============================================================================
def test_import_bills_happy_path_minimal_columns(tenant_id):
    with tenant_scope(tenant_id):
        xlsx = _workbook(
            ["name", "amount", "currency", "due_on"],
            [["Rent", 1500.00, "USD", "2026-02-01"], ["Internet", 59.99, "USD", "2026-02-05"]],
        )
        result = import_xlsx.import_bills_xlsx(file_bytes=xlsx)
        assert result.created == 2
        assert result.errors == []
        rent = Bill.objects.get(name="Rent")
        assert rent.amount_minor == 150000
        assert rent.currency == "USD"
        assert rent.due_on.isoformat() == "2026-02-01"


def test_import_bills_with_payee_category_and_recurrence(tenant_id):
    with tenant_scope(tenant_id):
        services.create_category(name="Housing", kind=CategoryKind.EXPENSE, currency="USD")
        xlsx = _workbook(
            ["name", "amount", "currency", "due_on", "payee", "category", "recurrence_frequency",
             "recurrence_interval", "notes"],
            [["Rent", 1500.00, "USD", "2026-02-01", "Sunrise Apartments", "Housing", "monthly", 1, "Unit 4B"]],
        )
        result = import_xlsx.import_bills_xlsx(file_bytes=xlsx)
        assert result.created == 1
        bill = Bill.objects.get(name="Rent")
        assert bill.payee.name == "Sunrise Apartments"
        assert bill.category.name == "Housing"
        assert bill.recurrence_frequency == "monthly"
        assert bill.recurrence_interval == 1
        assert bill.notes == "Unit 4B"


def test_import_bills_header_alias_tolerance(tenant_id):
    with tenant_scope(tenant_id):
        xlsx = _workbook(
            ["Bill", "Amount", "Currency", "Due"],
            [["Rent", 1500.00, "USD", "2026-02-01"]],
        )
        result = import_xlsx.import_bills_xlsx(file_bytes=xlsx)
        assert result.created == 1
        assert result.errors == []


def test_import_bills_missing_required_column_raises(tenant_id):
    with tenant_scope(tenant_id):
        xlsx = _workbook(["name", "amount"], [["Rent", 1500.00]])
        with pytest.raises(import_xlsx.ImportError_, match="currency"):
            import_xlsx.import_bills_xlsx(file_bytes=xlsx)


def test_import_bills_one_bad_row_does_not_abort_the_sheet(tenant_id):
    with tenant_scope(tenant_id):
        xlsx = _workbook(
            ["name", "amount", "currency", "due_on"],
            [
                ["Rent", "not-a-number", "USD", "2026-02-01"],  # bad amount
                ["Internet", 59.99, "USD", "2026-02-05"],  # fine
            ],
        )
        result = import_xlsx.import_bills_xlsx(file_bytes=xlsx)
        assert result.created == 1
        assert len(result.errors) == 1
        assert result.errors[0]["row"] == 2
        assert Bill.objects.filter(name="Internet").exists()
        assert not Bill.objects.filter(name="Rent").exists()


def test_import_bills_unresolved_category_falls_back_to_none(tenant_id):
    with tenant_scope(tenant_id):
        xlsx = _workbook(
            ["name", "amount", "currency", "due_on", "category"],
            [["Rent", 1500.00, "USD", "2026-02-01", "Does Not Exist"]],
        )
        result = import_xlsx.import_bills_xlsx(file_bytes=xlsx)
        assert result.created == 1
        assert result.errors == []
        assert Bill.objects.get(name="Rent").category_id is None


def test_import_bills_unresolved_payee_creates_one(tenant_id):
    with tenant_scope(tenant_id):
        xlsx = _workbook(
            ["name", "amount", "currency", "due_on", "payee"],
            [["Rent", 1500.00, "USD", "2026-02-01", "Brand New Landlord"]],
        )
        result = import_xlsx.import_bills_xlsx(file_bytes=xlsx)
        assert result.created == 1
        assert Bill.objects.get(name="Rent").payee.name == "Brand New Landlord"


def test_bills_template_round_trips_through_the_parser(tenant_id):
    with tenant_scope(tenant_id):
        result = import_xlsx.import_bills_xlsx(file_bytes=import_xlsx.bills_template_xlsx())
        assert result.created == len(import_xlsx.BILL_TEMPLATE_ROWS)
        assert result.errors == []


# =============================================================================
# Recurring — service layer
# =============================================================================
def _account(name="Checking", account_type=AccountType.CHECKING, currency="USD"):
    return services.create_financial_account(name=name, account_type=account_type, currency=currency)


def test_import_recurring_expense_happy_path(tenant_id):
    with tenant_scope(tenant_id):
        _account()
        services.create_category(name="Housing", kind=CategoryKind.EXPENSE, currency="USD")
        xlsx = _workbook(
            ["txn_type", "account", "category", "amount", "currency", "frequency", "starts_on"],
            [["expense", "Checking", "Housing", 1500.00, "USD", "monthly", "2026-02-01"]],
        )
        result = import_xlsx.import_recurring_xlsx(file_bytes=xlsx)
        assert result.created == 1
        assert result.errors == []
        rec = RecurringTransaction.objects.get()
        assert rec.amount_minor == 150000
        assert rec.category.name == "Housing"
        assert rec.financial_account.name == "Checking"


def test_import_recurring_transfer_resolves_counter_account_by_name(tenant_id):
    with tenant_scope(tenant_id):
        _account("Checking")
        _account("Savings", account_type=AccountType.SAVINGS)
        xlsx = _workbook(
            ["txn_type", "account", "counter_account", "amount", "currency", "frequency", "starts_on"],
            [["transfer", "Checking", "Savings", 200.00, "USD", "monthly", "2026-02-01"]],
        )
        result = import_xlsx.import_recurring_xlsx(file_bytes=xlsx)
        assert result.created == 1
        rec = RecurringTransaction.objects.get()
        assert rec.txn_type == "transfer"
        assert rec.counter_account.name == "Savings"


def test_import_recurring_unresolved_category_on_expense_row_is_an_error(tenant_id):
    """Unlike Bills, a recurring income/expense row genuinely needs a
    category — create_recurring_transaction's own validation raises, and the
    parser doesn't need to special-case it."""
    with tenant_scope(tenant_id):
        _account()
        xlsx = _workbook(
            ["txn_type", "account", "category", "amount", "currency", "frequency", "starts_on"],
            [["expense", "Checking", "Does Not Exist", 1500.00, "USD", "monthly", "2026-02-01"]],
        )
        result = import_xlsx.import_recurring_xlsx(file_bytes=xlsx)
        assert result.created == 0
        assert len(result.errors) == 1
        assert not RecurringTransaction.objects.exists()


def test_import_recurring_unresolved_account_is_an_error(tenant_id):
    with tenant_scope(tenant_id):
        xlsx = _workbook(
            ["txn_type", "account", "amount", "currency", "frequency", "starts_on"],
            [["income", "No Such Account", 1500.00, "USD", "monthly", "2026-02-01"]],
        )
        result = import_xlsx.import_recurring_xlsx(file_bytes=xlsx)
        assert result.created == 0
        assert len(result.errors) == 1


def test_import_recurring_missing_required_column_raises(tenant_id):
    with tenant_scope(tenant_id):
        xlsx = _workbook(["txn_type", "account"], [["expense", "Checking"]])
        with pytest.raises(import_xlsx.ImportError_):
            import_xlsx.import_recurring_xlsx(file_bytes=xlsx)


def test_recurring_template_round_trips_through_the_parser(tenant_id):
    with tenant_scope(tenant_id):
        _account("Checking")
        _account("Savings", account_type=AccountType.SAVINGS)
        services.create_category(name="Housing", kind=CategoryKind.EXPENSE, currency="USD")
        result = import_xlsx.import_recurring_xlsx(file_bytes=import_xlsx.recurring_template_xlsx())
        assert result.created == len(import_xlsx.RECURRING_TEMPLATE_ROWS)
        assert result.errors == []


# =============================================================================
# API level
# =============================================================================
def _uploaded_xlsx(filename, header, rows):
    from django.core.files.uploadedfile import SimpleUploadedFile

    content = _workbook(header, rows)
    return SimpleUploadedFile(
        filename, content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_api_bill_import(tenant_context):
    _, client = tenant_context
    upload = _uploaded_xlsx(
        "bills.xlsx", ["name", "amount", "currency", "due_on"], [["Rent", 1500.00, "USD", "2026-02-01"]]
    )
    resp = client.post("/api/v1/finance/bills/import/", {"file": upload}, format="multipart")
    assert resp.status_code == 201, resp.data
    assert resp.data["created"] == 1
    assert resp.data["errors"] == []


def test_api_bill_import_requires_a_file(tenant_context):
    _, client = tenant_context
    resp = client.post("/api/v1/finance/bills/import/", {}, format="multipart")
    assert resp.status_code == 400


def test_api_bill_import_template_download(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/finance/bills/import/")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert len(resp.content) > 0


def test_api_recurring_import(tenant_context):
    _, client = tenant_context
    client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD"},
        format="json",
    )
    client.post(
        "/api/v1/finance/categories/", {"name": "Salary", "kind": "income", "currency": "USD"}, format="json"
    )
    upload = _uploaded_xlsx(
        "recurring.xlsx",
        ["txn_type", "account", "category", "amount", "currency", "frequency", "starts_on"],
        [["income", "Checking", "Salary", 1500.00, "USD", "monthly", "2026-02-01"]],
    )
    resp = client.post("/api/v1/finance/recurring/import/", {"file": upload}, format="multipart")
    assert resp.status_code == 201, resp.data
    assert resp.data["created"] == 1


def test_api_recurring_import_template_download(tenant_context):
    _, client = tenant_context
    resp = client.get("/api/v1/finance/recurring/import/")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_api_bill_export(tenant_context):
    _, client = tenant_context
    client.post(
        "/api/v1/finance/bills/",
        {"name": "Rent", "amount_minor": 150000, "currency": "USD", "due_on": "2026-02-01"},
        format="json",
    )
    resp = client.get("/api/v1/finance/bills/export/")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv"
    body = b"".join(resp.streaming_content).decode()
    assert "Rent" in body


def test_api_recurring_export(tenant_context):
    _, client = tenant_context
    account = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD"},
        format="json",
    ).data
    category = client.post(
        "/api/v1/finance/categories/", {"name": "Housing", "kind": "expense", "currency": "USD"}, format="json"
    ).data
    client.post(
        "/api/v1/finance/recurring/",
        {
            "txn_type": "expense",
            "financial_account_id": account["id"],
            "category_id": category["id"],
            "amount_minor": 150000,
            "currency": "USD",
            "frequency": "monthly",
            "starts_on": "2026-02-01",
        },
        format="json",
    )
    resp = client.get("/api/v1/finance/recurring/export/")
    assert resp.status_code == 200
    body = b"".join(resp.streaming_content).decode()
    assert "Housing" in body
