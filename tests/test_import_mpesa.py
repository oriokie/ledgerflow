"""M-Pesa statement import.

No real statement is checked in, deliberately: an M-Pesa PDF is a complete
record of who somebody pays, when, and how much, and a test fixture is forever.
The classifier is exercised against the *shapes* of Details strings taken from
a real statement with the identities replaced, and the posting rules are
exercised against rows constructed in code.

What is pinned hardest is the pair of things that would corrupt somebody's
books quietly rather than loudly:

  * Fuliza is borrowing, so it must never reach income or spending;
  * re-importing an overlapping statement must post nothing twice.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from apps.finance import services as finance_services
from apps.finance.import_mpesa import (
    MpesaKind,
    MpesaRow,
    ParsedStatement,
    classify,
)
from apps.finance.import_mpesa_service import (
    FULIZA_ACCOUNT_NAME,
    import_parsed_statement,
)
from apps.finance.models import AccountType, CategoryKind, FinancialAccount, Transaction
from apps.finance.payees import get_or_create_payee
from apps.finance.selectors import account_current_balance_minor
from tests.factories import TenantFactory
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------- classifier
#
# One case per shape that appears in a real statement. These are the strings
# the parser has to survive; getting any of them wrong silently misfiles money.
@pytest.mark.parametrize(
    ("details", "expected_kind", "expected_who"),
    [
        # The charge rows must beat the transfer rows to the match, or every
        # fee is misread as a transfer to nobody.
        ("Customer Transfer of Funds Charge", MpesaKind.CHARGE, ""),
        ("Pay Bill Charge", MpesaKind.CHARGE, ""),
        ("Pay Merchant Charge", MpesaKind.CHARGE, ""),
        ("Withdrawal Charge", MpesaKind.CHARGE, ""),
        # Fuliza: the two that are not income and not spending.
        ("OverDraft of Credit Party", MpesaKind.OVERDRAFT_ADVANCE, ""),
        ("OD Loan Repayment to 232323 - M-PESA Overdraw", MpesaKind.OVERDRAFT_REPAYMENT, ""),
        # Person to person, with and without the Fuliza rail.
        ("Customer Transfer to - 254712345678 JANE DOE", MpesaKind.SEND_MONEY, "JANE DOE"),
        ("Customer Transfer to - 0712***678 JANE DOE", MpesaKind.SEND_MONEY, "JANE DOE"),
        ("Customer Transfer Fuliza MPesa to - 254712345678 JOHN ROE", MpesaKind.SEND_MONEY, "JOHN ROE"),
        ("Customer Payment to Small Business to - 254712345678 A TRADER", MpesaKind.SEND_MONEY, "A TRADER"),
        # Paybill: the account reference must be stripped, or every payment to
        # the same biller looks like a different biller.
        ("Pay Bill Online to 888880 - KPLC PREPAID Acc. 0141234", MpesaKind.PAYBILL, "KPLC PREPAID"),
        ("Pay Bill Online Fuliza M-Pesa to 714777 - LOOP C2B Acc. 0721234", MpesaKind.PAYBILL, "LOOP C2B"),
        # Till.
        (
            "Merchant Payment Online to 605000 - Naivas Kahawa Sukari 2",
            MpesaKind.BUY_GOODS,
            "Naivas Kahawa Sukari 2",
        ),
        ("Merchant Payment to 630000 - AYOLA FOODS LIMITED", MpesaKind.BUY_GOODS, "AYOLA FOODS LIMITED"),
        # Money in. Salary must beat the generic bank credit.
        (
            "Salary Payment from 504900 - EXAMPLE BANK via API. Original conversation ID is X.",
            MpesaKind.SALARY,
            "EXAMPLE BANK",
        ),
        (
            "Business Payment from 300600 - EXAMPLE BULK via API. Original conversation ID is Y.",
            MpesaKind.RECEIVE,
            "EXAMPLE BULK",
        ),
        ("Funds received from - 254712345678 ALEX ROE", MpesaKind.RECEIVE, "ALEX ROE"),
        (
            "Receive International Transfer From 413000 - SOME REMITTER LIMITED.",
            MpesaKind.RECEIVE,
            "SOME REMITTER LIMITED",
        ),
        # Cash and airtime.
        (
            "Customer Withdrawal At Agent Till 100200 - SOME AGENCY SHOP",
            MpesaKind.AGENT_WITHDRAWAL,
            "SOME AGENCY SHOP",
        ),
        ("Airtime Purchase", MpesaKind.AIRTIME, ""),
    ],
)
def test_classify(details, expected_kind, expected_who):
    kind, who = classify(details)
    assert kind is expected_kind
    assert who == expected_who


def test_unknown_details_are_other_not_a_guess():
    """An unrecognised row is labelled unknown rather than forced into the
    nearest bucket — a wrong category is harder to spot than a blank one."""
    kind, who = classify("Some Future Product We Have Never Seen")
    assert kind is MpesaKind.OTHER
    assert who == ""


# ------------------------------------------------------------------ identity
def test_rows_sharing_a_receipt_get_distinct_ids():
    """A transfer and its charge share one receipt number. If identity were the
    receipt alone, the charge would be treated as a duplicate and dropped."""
    transfer = _row("UH543273X9", -30000, "Customer Transfer to - 254712345678 JANE DOE")
    charge = _row("UH543273X9", -700, "Customer Transfer of Funds Charge")
    assert transfer.external_id != charge.external_id


def test_external_id_is_stable_across_parses():
    a = _row("UH543273X9", -30000, "Customer Transfer to - 254712345678 JANE DOE")
    b = _row("UH543273X9", -30000, "Customer Transfer to - 254712345678 JANE DOE")
    assert a.external_id == b.external_id


# ------------------------------------------------------------- reconciliation
def test_reconciles_against_the_statements_own_totals():
    statement = _statement(
        [_row("A1", 10000, "Funds received from - 254712345678 X Y"), _row("A2", -4000, "Pay Bill Charge")]
    )
    statement.declared_paid_in_minor = 10000
    statement.declared_withdrawn_minor = 4000
    assert statement.reconciles is True


def test_reconciliation_fails_loudly_when_rows_are_missing():
    statement = _statement([_row("A1", 10000, "Funds received from - 254712345678 X Y")])
    statement.declared_paid_in_minor = 50000  # statement claims more than we read
    statement.declared_withdrawn_minor = 0
    assert statement.reconciles is False
    assert "500.00" in statement.discrepancy()


def test_reconciliation_is_unknown_not_true_without_totals():
    """A statement with no printed totals cannot be checked. Reporting that as
    success would make an unverifiable import look verified."""
    assert _statement([_row("A1", 10000, "Airtime Purchase")]).reconciles is None


# ------------------------------------------------------------------- posting
def test_fuliza_never_counts_as_income_or_spending():
    """The property the whole design exists for."""
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        statement = _statement(
            [
                _row("F1", 50000, "OverDraft of Credit Party"),  # borrowed 500
                _row("F2", -50000, "OD Loan Repayment to 232323 - M-PESA Overdraw"),
                _row("S1", -20000, "Merchant Payment Online to 605000 - A SHOP"),  # real spend 200
                _row("I1", 80000, "Salary Payment from 504900 - EXAMPLE BANK via API."),
            ]
        )
        result = import_parsed_statement(financial_account=account, statement=statement)
        assert result.imported == 4
        assert not result.errors

        income = _sum(account, positive=True)
        spending = _sum(account, positive=False)

        # The salary, and nothing else. The 500 borrowed is excluded.
        assert income == 80000
        # The shop, and nothing else. The 500 repaid is excluded.
        assert spending == 20000

        assert result.overdraft_advanced_minor == 50000
        assert result.overdraft_repaid_minor == 50000


def test_overdraft_creates_a_credit_line_carrying_the_balance():
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        import_parsed_statement(
            financial_account=account,
            statement=_statement([_row("F1", 50000, "OverDraft of Credit Party")]),
        )
        fuliza = FinancialAccount.objects.get(name=FULIZA_ACCOUNT_NAME)
        assert fuliza.account_type == AccountType.LOAN
        # Crediting a liability increases what is owed.
        assert account_current_balance_minor(fuliza) == 50000
        # And the cash actually arrived, on top of the opening balance.
        assert account_current_balance_minor(account) == 500_000 + 50000


def test_partial_history_negative_fuliza_is_explained_not_hidden():
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        # Repayment with no matching advance: the borrowing predates the window.
        result = import_parsed_statement(
            financial_account=account,
            statement=_statement(
                [
                    _row("I1", 100000, "Salary Payment from 504900 - EXAMPLE BANK via API."),
                    _row("F1", -30000, "OD Loan Repayment to 232323 - M-PESA Overdraw"),
                ]
            ),
        )
        assert any("more repaid than borrowed" in n for n in result.notices)


def test_reimport_posts_nothing_twice():
    """Statements overlap by design — people pull three months every month."""
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        statement = _statement(
            [
                _row("A1", -30000, "Customer Transfer to - 254712345678 JANE DOE"),
                _row("A1", -700, "Customer Transfer of Funds Charge"),
                _row("A2", 90000, "Salary Payment from 504900 - EXAMPLE BANK via API."),
            ]
        )
        first = import_parsed_statement(financial_account=account, statement=statement)
        assert first.imported == 3

        second = import_parsed_statement(financial_account=account, statement=statement)
        assert second.imported == 0
        assert second.skipped_duplicate == 3
        assert Transaction.objects.filter(financial_account=account).count() == 3


def test_reimport_is_idempotent_for_overdrafts_too():
    """Regression: the advance leg posts on the Fuliza account, so stamping the
    wrong leg made every advance re-import as new on the second run."""
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        statement = _statement(
            [
                _row("F1", 50000, "OverDraft of Credit Party"),
                _row("F2", -50000, "OD Loan Repayment to 232323 - M-PESA Overdraw"),
            ]
        )
        import_parsed_statement(financial_account=account, statement=statement)
        second = import_parsed_statement(financial_account=account, statement=statement)
        assert second.imported == 0
        assert second.skipped_duplicate == 2


def test_charges_land_in_one_category():
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        result = import_parsed_statement(
            financial_account=account,
            statement=_statement(
                [
                    _row("A1", -700, "Customer Transfer of Funds Charge"),
                    _row("A2", -5700, "Pay Bill Charge"),
                ]
            ),
        )
        assert result.charges_minor == 6400
        categories = {t.category.name for t in Transaction.objects.filter(financial_account=account)}
        assert categories == {"M-Pesa Charges"}


def test_a_known_payee_categorises_the_row():
    """The learning half: categorise a payee once, and later imports follow."""
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        groceries = finance_services.create_category(
            name="Groceries", kind=CategoryKind.EXPENSE, currency="KES"
        )
        payee, _ = get_or_create_payee(name="Naivas Kahawa Sukari 2", default_category=groceries)

        result = import_parsed_statement(
            financial_account=account,
            statement=_statement(
                [
                    _row("A1", -120000, "Merchant Payment Online to 605000 - Naivas Kahawa Sukari 2"),
                ]
            ),
        )
        assert result.auto_categorised == 1
        txn = Transaction.objects.get(financial_account=account)
        assert txn.category_id == groceries.id
        assert txn.payee_id == payee.id


def test_unknown_payee_is_left_uncategorised_for_review():
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        import_parsed_statement(
            financial_account=account,
            statement=_statement(
                [
                    _row("A1", -120000, "Merchant Payment Online to 999999 - A NEW SHOP"),
                ]
            ),
        )
        txn = Transaction.objects.get(financial_account=account)
        assert txn.category.name == "Uncategorized"
        # …but the payee still exists, so categorising it once teaches the rest.
        assert txn.payee.name == "A NEW SHOP"


def test_non_kes_account_is_refused():
    """Posting shillings into a dollar account would be wrong by ~130x and look
    entirely plausible on screen."""
    from apps.finance.import_mpesa import MpesaParseError

    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        usd = finance_services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        with pytest.raises(MpesaParseError, match="KES"):
            import_parsed_statement(
                financial_account=usd,
                statement=_statement([_row("A1", -700, "Pay Bill Charge")]),
            )


def test_one_bad_row_does_not_abort_the_import():
    """Regression: the per-row `except` sat inside the outer atomic block with
    no savepoint.

    The failure must come from a statement *outside* the posting services —
    each is `@transaction.atomic`, so an error raised inside one rolls back to
    its own savepoint harmlessly. The exposed statement is `_stamp`, whose bare
    `save()` writes `external_id` into a 128-character column. A receipt long
    enough to overflow it reproduces exactly the shape of failure seen against
    a real statement: without a savepoint the transaction is marked broken, and
    every later row raises TransactionManagementError instead of importing.
    """
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        statement = _statement(
            [
                _row("R" * 200, -700, "Pay Bill Charge", when=datetime(2026, 6, 1, 9, 0)),
                _row(
                    "A2",
                    90000,
                    "Salary Payment from 504900 - EXAMPLE BANK via API.",
                    when=datetime(2026, 6, 2, 9, 0),
                ),
                _row("A3", -1500, "Pay Bill Charge", when=datetime(2026, 6, 3, 9, 0)),
            ]
        )

        result = import_parsed_statement(financial_account=account, statement=statement)
        assert len(result.errors) == 1, result.errors
        assert result.imported == 2, "rows after the failure must still land"
        assert Transaction.objects.filter(financial_account=account).count() == 2


# ------------------------------------------------------------------ helpers
def _row(receipt: str, amount_minor: int, details: str, when: datetime | None = None) -> MpesaRow:
    kind, who = classify(details)
    return MpesaRow(
        receipt=receipt,
        completed_at=when or datetime(2026, 5, 15, 9, 30, 0),
        details=details,
        status="Completed",
        amount_minor=amount_minor,
        balance_minor=None,
        kind=kind,
        counterparty=who,
    )


def _statement(rows: list[MpesaRow]) -> ParsedStatement:
    return ParsedStatement(
        rows=rows, period_start="06 May 2026", period_end="06 Aug 2026", customer_name="TEST USER"
    )


def _mpesa_account() -> FinancialAccount:
    return finance_services.create_financial_account(
        name="M-Pesa", account_type=AccountType.CASH, currency="KES", opening_balance_minor=500_000
    )


def _sum(account: FinancialAccount, *, positive: bool) -> int:
    """Income or spending, excluding transfers — which is exactly how the rest
    of the app computes them."""
    qs = Transaction.objects.filter(financial_account=account, transfer_group__isnull=True)
    qs = qs.filter(amount_minor__gt=0) if positive else qs.filter(amount_minor__lt=0)
    return abs(sum(t.amount_minor for t in qs))


# ---------------------------------------------------------------------- API
#
# The endpoint is tested with the parser patched out. Its job is validation,
# routing and not leaking the password — none of which needs a real PDF, and a
# real PDF is the one thing that must never enter this repository.
def _fake_pdf():
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile("statement.pdf", b"%PDF-1.4 not really", content_type="application/pdf")


@pytest.fixture
def _patched_parser(monkeypatch):
    statement = _statement(
        [
            _row("A1", -30000, "Customer Transfer to - 254712345678 JANE DOE"),
            _row("A1", -700, "Customer Transfer of Funds Charge"),
            _row("A2", 90000, "Salary Payment from 504900 - EXAMPLE BANK via API."),
        ]
    )
    statement.declared_paid_in_minor = 90000
    statement.declared_withdrawn_minor = 30700
    monkeypatch.setattr(
        "apps.finance.import_mpesa_service.parse_statement",
        lambda file_bytes, password="": statement,
    )
    return statement


def test_preview_describes_without_posting(tenant_context, _patched_parser):
    """Uploading three months of your financial life is not a step to take on
    trust: the preview shows what is in the file, and whether it adds up,
    before anything is written."""
    membership, client = tenant_context

    resp = client.post(
        "/api/v1/finance/transactions/import/mpesa/?preview=1",
        {"file": _fake_pdf(), "password": "not-the-real-one"},
        format="multipart",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["rows_found"] == 3
    assert resp.data["reconciles"] is True
    assert resp.data["by_kind"]["charge"]["count"] == 1
    # Nothing was written.
    with tenant_scope(membership.tenant_id):
        assert Transaction.objects.count() == 0


def test_import_requires_an_account(tenant_context, _patched_parser):
    _, client = tenant_context
    resp = client.post(
        "/api/v1/finance/transactions/import/mpesa/",
        {"file": _fake_pdf(), "password": "x"},
        format="multipart",
    )
    assert resp.status_code == 400
    assert "account_id" in resp.data["detail"]


def test_import_posts_and_is_idempotent_over_http(tenant_context, _patched_parser):
    membership, client = tenant_context
    with tenant_scope(membership.tenant_id):
        account = _mpesa_account()

    payload = {"file": _fake_pdf(), "password": "not-the-real-one", "account_id": str(account.id)}
    resp = client.post("/api/v1/finance/transactions/import/mpesa/", payload, format="multipart")
    assert resp.status_code == 201, resp.data
    assert resp.data["imported"] == 3
    assert resp.data["reconciles"] is True

    again = client.post(
        "/api/v1/finance/transactions/import/mpesa/",
        {"file": _fake_pdf(), "password": "not-the-real-one", "account_id": str(account.id)},
        format="multipart",
    )
    assert again.data["imported"] == 0
    assert again.data["skipped_duplicate"] == 3


def test_a_missing_file_is_refused(tenant_context):
    _, client = tenant_context
    resp = client.post("/api/v1/finance/transactions/import/mpesa/", {"password": "x"}, format="multipart")
    assert resp.status_code == 400


def test_the_password_is_never_echoed_back(tenant_context, _patched_parser):
    """It unlocks a bank statement. It must not appear in a response body, and
    it is not stored anywhere either."""
    membership, client = tenant_context
    with tenant_scope(membership.tenant_id):
        account = _mpesa_account()

    resp = client.post(
        "/api/v1/finance/transactions/import/mpesa/",
        {"file": _fake_pdf(), "password": "not-the-real-one", "account_id": str(account.id)},
        format="multipart",
    )
    assert "not-the-real-one" not in str(resp.data)


def test_a_bad_password_reports_plainly(tenant_context, monkeypatch):
    """The one error the user can actually fix, so it must say so rather than
    surfacing a pdfminer exception."""
    from apps.finance.import_mpesa import MpesaParseError

    def _boom(file_bytes, password=""):
        raise MpesaParseError("Could not open the statement — check the password Safaricom sent with it.")

    monkeypatch.setattr("apps.finance.import_mpesa_service.parse_statement", _boom)
    _, client = tenant_context

    resp = client.post(
        "/api/v1/finance/transactions/import/mpesa/?preview=1",
        {"file": _fake_pdf(), "password": "wrong"},
        format="multipart",
    )
    assert resp.status_code == 400
    assert "password" in resp.data["detail"].lower()


# ------------------------------------------------------------- date window
#
# The window exists for one reason: a transaction somebody typed in has no
# external_id and never will, so the importer's idempotency cannot see it. A
# statement overlapping a hand-tracked period records that period twice.
def test_a_start_date_excludes_earlier_rows():
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        statement = _statement(
            [
                _row("A1", -10000, "Pay Bill Charge", when=datetime(2026, 5, 10, 9, 0)),
                _row("A2", -20000, "Pay Bill Charge", when=datetime(2026, 6, 15, 9, 0)),
                _row("A3", -30000, "Pay Bill Charge", when=datetime(2026, 7, 20, 9, 0)),
            ]
        )
        result = import_parsed_statement(
            financial_account=account, statement=statement, from_date=date(2026, 6, 1)
        )
        assert result.rows_found == 3
        assert result.rows_in_range == 2
        assert result.imported == 2
        assert Transaction.objects.filter(financial_account=account).count() == 2


def test_both_bounds_are_inclusive():
    """ "1 June to 30 June" means the whole of both days. An exclusive end
    silently drops the last day's activity, which is the day people care most
    about when they are catching up."""
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        statement = _statement(
            [
                _row("A1", -10000, "Pay Bill Charge", when=datetime(2026, 6, 1, 0, 5)),
                _row("A2", -20000, "Pay Bill Charge", when=datetime(2026, 6, 30, 23, 55)),
            ]
        )
        result = import_parsed_statement(
            financial_account=account,
            statement=statement,
            from_date=date(2026, 6, 1),
            to_date=date(2026, 6, 30),
        )
        assert result.imported == 2


def test_reconciliation_still_describes_the_whole_statement():
    """Regression guard. Reconciliation answers "did we read the file
    correctly", which is about parsing, not about what the user kept. Checking
    a filtered subset against the statement's printed totals would fail every
    time a window was used, and would train people to ignore the one signal
    that catches a genuinely broken parse."""
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        statement = _statement(
            [
                _row("A1", -10000, "Pay Bill Charge", when=datetime(2026, 5, 10, 9, 0)),
                _row("A2", -20000, "Pay Bill Charge", when=datetime(2026, 7, 20, 9, 0)),
            ]
        )
        statement.declared_paid_in_minor = 0
        statement.declared_withdrawn_minor = 30000  # both rows

        result = import_parsed_statement(
            financial_account=account, statement=statement, from_date=date(2026, 7, 1)
        )
        assert result.imported == 1
        assert result.reconciles is True, "the parse was complete; only the import was narrowed"


def test_overlapping_manual_entries_are_flagged():
    """The safety net for someone who does not set a window. Manual entries
    cannot be matched against statement rows, so the honest move is to say so
    rather than to guess or to silently double-count."""
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        groceries = finance_services.create_category(
            name="Groceries", kind=CategoryKind.EXPENSE, currency="KES"
        )
        finance_services.record_expense(
            financial_account=account,
            category=groceries,
            amount_minor=20000,
            occurred_at=_aware_dt(2026, 6, 15),
            memo="Typed in by hand",
        )

        result = import_parsed_statement(
            financial_account=account,
            statement=_statement(
                [
                    _row("A1", -10000, "Pay Bill Charge", when=datetime(2026, 6, 1, 9, 0)),
                    _row("A2", -20000, "Pay Bill Charge", when=datetime(2026, 6, 30, 9, 0)),
                ]
            ),
        )
        assert any("did not come from a statement import" in n for n in result.notices)


def test_no_overlap_warning_when_the_period_is_clean():
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        result = import_parsed_statement(
            financial_account=account,
            statement=_statement([_row("A1", -10000, "Pay Bill Charge", when=datetime(2026, 6, 1, 9, 0))]),
        )
        assert not any("did not come from a statement import" in n for n in result.notices)


def test_reimporting_does_not_warn_about_its_own_earlier_rows():
    """The warning must fire on *manual* entries only. If a second import
    warned about the first import's rows, it would cry wolf on the single most
    common action there is."""
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        statement = _statement([_row("A1", -10000, "Pay Bill Charge", when=datetime(2026, 6, 1, 9, 0))])
        import_parsed_statement(financial_account=account, statement=statement)
        second = import_parsed_statement(financial_account=account, statement=statement)
        assert not any("did not come from a statement import" in n for n in second.notices)


def test_window_is_reported_back():
    tenant = TenantFactory()
    with tenant_scope(tenant.id):
        account = _mpesa_account()
        result = import_parsed_statement(
            financial_account=account,
            statement=_statement([_row("A1", -10000, "Pay Bill Charge", when=datetime(2026, 6, 1, 9, 0))]),
            from_date=date(2026, 5, 1),
            to_date=date(2026, 6, 30),
        )
        assert result.as_dict()["from_date"] == "2026-05-01"
        assert result.as_dict()["to_date"] == "2026-06-30"


def test_bad_dates_are_refused_by_the_api(tenant_context, _patched_parser):
    membership, client = tenant_context
    with tenant_scope(membership.tenant_id):
        account = _mpesa_account()

    bad = client.post(
        "/api/v1/finance/transactions/import/mpesa/",
        {
            "file": _fake_pdf(),
            "password": "x",
            "account_id": str(account.id),
            "from_date": "15/06/2026",
        },
        format="multipart",
    )
    assert bad.status_code == 400
    assert "YYYY-MM-DD" in bad.data["detail"]

    backwards = client.post(
        "/api/v1/finance/transactions/import/mpesa/",
        {
            "file": _fake_pdf(),
            "password": "x",
            "account_id": str(account.id),
            "from_date": "2026-07-01",
            "to_date": "2026-06-01",
        },
        format="multipart",
    )
    assert backwards.status_code == 400


def test_blank_dates_mean_no_bound_not_year_one(tenant_context, _patched_parser):
    """An empty form field is "no bound". Read as a date it would become
    0001-01-01 and quietly exclude the entire statement."""
    membership, client = tenant_context
    with tenant_scope(membership.tenant_id):
        account = _mpesa_account()

    resp = client.post(
        "/api/v1/finance/transactions/import/mpesa/",
        {
            "file": _fake_pdf(),
            "password": "x",
            "account_id": str(account.id),
            "from_date": "",
            "to_date": "",
        },
        format="multipart",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["imported"] == 3


def test_preview_reports_a_daily_histogram(tenant_context, _patched_parser):
    """The client needs to say how many rows a chosen window covers. Shipping a
    count per day is enough for that and small — a quarterly statement is about
    ninety keys — where shipping every row would not be."""
    _, client = tenant_context
    resp = client.post(
        "/api/v1/finance/transactions/import/mpesa/?preview=1",
        {"file": _fake_pdf(), "password": "not-the-real-one"},
        format="multipart",
    )
    assert resp.status_code == 200, resp.data
    assert sum(resp.data["by_day"].values()) == resp.data["rows_found"]
    assert resp.data["first_seen"] <= resp.data["last_seen"]


def _aware_dt(y, m, d):
    from django.utils import timezone as _tz

    return _tz.make_aware(datetime(y, m, d, 12, 0), _tz.get_current_timezone())
