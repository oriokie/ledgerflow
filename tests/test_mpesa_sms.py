"""M-Pesa SMS paste: parse the confirmation, post it, skip it on statement import.

The property that must not regress: a receipt pasted from the phone and later
seen on a statement is one movement, not two. Matching on the statement's
composite external_id cannot see an SMS — the Details wording is different —
so identity is the receipt plus the signed amount.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from apps.finance import services as finance_services
from apps.finance.import_mpesa import MpesaKind
from apps.finance.import_mpesa_service import import_parsed_statement
from apps.finance.models import AccountType, CategoryKind, Transaction
from apps.finance.mpesa_sms import MpesaSmsParseError, parse_sms, sms_external_id
from apps.finance.mpesa_sms_service import (
    MPESA_ACCOUNT_NAME,
    capture_mpesa_sms,
    get_or_create_default_mpesa_account,
)
from tests.factories import TenantFactory
from tests.test_import_mpesa import _mpesa_account, _row, _statement
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


SAMPLE_SEND = (
    "UI94368KUX Confirmed. Ksh250.00 sent to JOHN  NDUNGU 0707750700 on 9/9/26 at "
    "3:29 PM. New M-PESA balance is Ksh0.00. Transaction cost, Ksh7.00.  Amount "
    "you can transact within the day is 498,650.00. See all your balances now "
    "https://saf.cx/iqIzU"
)

SAMPLE_RECEIVE = (
    "QBR5XYZ12A Confirmed. You have received Ksh1,500.00 from JANE DOE 254712345678 "
    "on 13/9/26 at 8:05 AM. New M-PESA balance is Ksh1,500.00."
)

SAMPLE_PAYBILL = (
    "TIA9ABCDE1 Confirmed. Ksh200.00 sent to KPLC PREPAID for account 0141234 on "
    "1/10/26 at 7:15 PM. New M-PESA balance is Ksh50.00. Transaction cost, Ksh3.00."
)

SAMPLE_TILL = (
    "NH7KKK1111 Confirmed. Ksh50.00 paid to NAIVAS SUPERMARKET. on 2/10/26 at "
    "12:01 PM. New M-PESA balance is Ksh10.00. Transaction cost, Ksh0.00."
)


def test_send_money_extracts_receipt_amount_date_and_fee():
    parsed = parse_sms(SAMPLE_SEND)
    assert parsed.receipt == "UI94368KUX"
    assert parsed.amount_minor == -25_000
    assert parsed.charge_minor == 700
    assert parsed.counterparty == "JOHN NDUNGU"
    assert parsed.kind is MpesaKind.SEND_MONEY
    assert parsed.occurred_at == datetime(2026, 9, 9, 15, 29)
    assert parsed.balance_minor == 0


def test_received_money_is_an_inflow_and_day_first_dates_parse():
    """13/9/26 cannot be M/D — if we guessed US order it would raise."""
    parsed = parse_sms(SAMPLE_RECEIVE)
    assert parsed.is_inflow
    assert parsed.amount_minor == 150_000
    assert parsed.charge_minor == 0
    assert parsed.counterparty == "JANE DOE"
    assert parsed.occurred_at == datetime(2026, 9, 13, 8, 5)


def test_paybill_is_not_a_person_to_person_transfer():
    parsed = parse_sms(SAMPLE_PAYBILL)
    assert parsed.kind is MpesaKind.PAYBILL
    assert parsed.counterparty == "KPLC PREPAID"
    assert parsed.amount_minor == -20_000
    assert parsed.charge_minor == 300


def test_till_payment():
    parsed = parse_sms(SAMPLE_TILL)
    assert parsed.kind is MpesaKind.BUY_GOODS
    assert parsed.counterparty == "NAIVAS SUPERMARKET"
    assert parsed.charge_minor == 0


def test_a_blank_paste_is_refused():
    with pytest.raises(MpesaSmsParseError, match="Paste"):
        parse_sms("   ")


def test_a_random_message_is_refused_plainly():
    with pytest.raises(MpesaSmsParseError, match="doesn't look like"):
        parse_sms("Hello, this is not M-Pesa")


def test_capture_posts_to_a_default_mpesa_account_and_deducts_the_amount():
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        result = capture_mpesa_sms(message=SAMPLE_SEND, purpose="Fare")
        assert result.account.name == MPESA_ACCOUNT_NAME
        assert result.account.currency == "KES"
        assert result.already_recorded is False
        assert result.transaction.amount_minor == -25_000
        assert result.transaction.memo == "Fare"
        assert result.transaction.metadata["mpesa_receipt"] == "UI94368KUX"
        assert result.charge is not None
        assert result.charge.amount_minor == -700
        assert result.transaction.external_id == sms_external_id("UI94368KUX", -25_000)
        from apps.finance.selectors import account_current_balance_minor

        # Opening 0, then 250 + 7 out.
        assert account_current_balance_minor(result.account) == -25_700


def test_capture_reuses_an_existing_account_named_mpesa():
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        existing = finance_services.create_financial_account(
            name="M-Pesa",
            account_type=AccountType.CASH,
            currency="KES",
            opening_balance_minor=10_000,
        )
        result = capture_mpesa_sms(message=SAMPLE_SEND)
        assert result.account.id == existing.id
        from apps.finance.selectors import account_current_balance_minor

        assert account_current_balance_minor(existing) == 10_000 - 25_000 - 700


def test_repasting_the_same_sms_does_not_post_twice():
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        first = capture_mpesa_sms(message=SAMPLE_SEND, purpose="Fare")
        second = capture_mpesa_sms(message=SAMPLE_SEND, purpose="Uber")
        assert second.already_recorded is True
        assert second.transaction.id == first.transaction.id
        assert second.transaction.memo == "Uber"
        assert (
            Transaction.objects.filter(metadata__mpesa_receipt="UI94368KUX").count() == 2
        )  # payment + charge


def test_category_is_optional_and_lands_in_uncategorized():
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        result = capture_mpesa_sms(message=SAMPLE_SEND)
        assert result.transaction.category.name == "Uncategorized"


def test_an_explicit_category_is_stored():
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        groceries = finance_services.create_category(
            name="Groceries", kind=CategoryKind.EXPENSE, currency="KES"
        )
        result = capture_mpesa_sms(message=SAMPLE_SEND, category=groceries)
        assert result.transaction.category_id == groceries.id


def test_statement_import_skips_a_pasted_receipt_instead_of_doubling_it():
    """The reason this feature exists: the PDF must not record the SMS twice."""
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        capture_mpesa_sms(message=SAMPLE_SEND, purpose="Fare")
        account = get_or_create_default_mpesa_account()
        statement = _statement(
            [
                _row(
                    "UI94368KUX",
                    -25_000,
                    "Customer Transfer to - 254707750700 JOHN NDUNGU",
                    when=datetime(2026, 9, 9, 15, 29),
                ),
                _row(
                    "UI94368KUX",
                    -700,
                    "Customer Transfer of Funds Charge",
                    when=datetime(2026, 9, 9, 15, 29),
                ),
                _row("OTHER1", -1_000, "Airtime Purchase", when=datetime(2026, 9, 10, 9, 0)),
            ]
        )
        imported = import_parsed_statement(financial_account=account, statement=statement)
        assert imported.skipped_duplicate == 2
        assert imported.imported == 1
        # Still one payment and one charge for that receipt, plus the new airtime.
        assert Transaction.objects.filter(metadata__mpesa_receipt="UI94368KUX").count() == 2
        fare = Transaction.objects.get(external_id=statement.rows[0].external_id)
        assert fare.memo == "Fare"
        assert fare.amount_minor == -25_000


def test_a_statement_row_can_receive_a_purpose_from_a_later_paste():
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        statement = _statement(
            [
                _row(
                    "UI94368KUX",
                    -25_000,
                    "Customer Transfer to - 254707750700 JOHN NDUNGU",
                    when=datetime(2026, 9, 9, 15, 29),
                ),
            ]
        )
        import_parsed_statement(financial_account=account, statement=statement)
        result = capture_mpesa_sms(message=SAMPLE_SEND, purpose="School fees")
        assert result.already_recorded is True
        assert result.transaction.memo == "School fees"
        assert Transaction.objects.filter(amount_minor=-25_000).count() == 1


def test_api_paste_and_list(tenant_context):
    _, client = tenant_context
    resp = client.post(
        "/api/v1/finance/mpesa-sms/",
        {"message": SAMPLE_SEND, "purpose": "Fare"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["receipt"] == "UI94368KUX"
    assert resp.data["amount_minor"] == -25_000
    assert resp.data["charge_minor"] == -700
    assert resp.data["purpose"] == "Fare"
    assert resp.data["already_recorded"] is False
    assert resp.data["account_name"] == MPESA_ACCOUNT_NAME

    listing = client.get("/api/v1/finance/mpesa-sms/")
    assert listing.status_code == 200
    assert len(listing.data) == 1
    assert listing.data[0]["receipt"] == "UI94368KUX"

    again = client.post("/api/v1/finance/mpesa-sms/", {"message": SAMPLE_SEND}, format="json")
    assert again.status_code == 200
    assert again.data["already_recorded"] is True


def test_api_rejects_a_non_mpesa_message(tenant_context):
    _, client = tenant_context
    resp = client.post("/api/v1/finance/mpesa-sms/", {"message": "not a confirmation"}, format="json")
    assert resp.status_code == 400
    assert "M-Pesa" in resp.data["detail"]
