"""Service-layer tests for the modules added to close out the financial
engine: wallets, payees, tags, attachments, and safe transaction editing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from apps.finance import attachments as attachment_service
from apps.finance import payees as payee_service
from apps.finance import selectors, services
from apps.finance import tagging as tag_service
from apps.finance import wallets as wallet_service
from apps.finance.models import AccountType, AttachmentStatus, CategoryKind
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


def _now():
    return datetime.now(UTC)


def _seed():
    checking = services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency="USD"
    )
    groceries = services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
    salary = services.create_category(name="Salary", kind=CategoryKind.INCOME, currency="USD")
    return checking, groceries, salary


# --------------------------------------------------------------- wallets
def test_create_wallet(tenant_id):
    with tenant_scope(tenant_id):
        wallet = wallet_service.create_wallet(name="Travel Fund")
        assert wallet.name == "Travel Fund"
        assert wallet.is_default is False


def test_only_one_default_wallet(tenant_id):
    with tenant_scope(tenant_id):
        w1 = wallet_service.create_wallet(name="Main", is_default=True)
        w2 = wallet_service.create_wallet(name="Backup", is_default=True)
        w1.refresh_from_db()
        w2.refresh_from_db()
        assert w1.is_default is False
        assert w2.is_default is True


def test_wallet_balances_per_currency_no_cross_summing(tenant_id):
    with tenant_scope(tenant_id):
        wallet = wallet_service.create_wallet(name="Global")
        usd_acct = services.create_financial_account(
            name="US Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        eur_acct = services.create_financial_account(
            name="EU Checking", account_type=AccountType.CHECKING, currency="EUR"
        )
        wallet_service.assign_account_to_wallet(financial_account=usd_acct, wallet=wallet)
        wallet_service.assign_account_to_wallet(financial_account=eur_acct, wallet=wallet)

        usd_income = services.create_category(name="USD In", kind=CategoryKind.INCOME, currency="USD")
        eur_income = services.create_category(name="EUR In", kind=CategoryKind.INCOME, currency="EUR")
        services.record_income(
            financial_account=usd_acct, category=usd_income, amount_minor=10000, occurred_at=_now()
        )
        services.record_income(
            financial_account=eur_acct, category=eur_income, amount_minor=5000, occurred_at=_now()
        )

        balances = {b.currency: b.balance_minor for b in selectors.wallet_balances(wallet)}
        assert balances == {"USD": 10000, "EUR": 5000}  # never summed together


def test_unassigning_account_from_wallet(tenant_id):
    with tenant_scope(tenant_id):
        wallet = wallet_service.create_wallet(name="Travel")
        acct = services.create_financial_account(
            name="Checking", account_type=AccountType.CHECKING, currency="USD"
        )
        wallet_service.assign_account_to_wallet(financial_account=acct, wallet=wallet)
        acct.refresh_from_db()
        assert acct.wallet_id == wallet.id

        wallet_service.assign_account_to_wallet(financial_account=acct, wallet=None)
        acct.refresh_from_db()
        assert acct.wallet_id is None
        assert selectors.wallet_balances(wallet) == []


def test_wallet_name_uniqueness(tenant_id):
    from django.db import IntegrityError

    with tenant_scope(tenant_id):
        wallet_service.create_wallet(name="Main")
        with pytest.raises(IntegrityError):
            wallet_service.create_wallet(name="Main")


# --------------------------------------------------------------- payees
def test_create_payee_normalizes_name(tenant_id):
    with tenant_scope(tenant_id):
        payee = payee_service.create_payee(name="  Trader Joe's  ")
        assert payee.name == "Trader Joe's"
        assert payee.normalized_name == "trader joe's"


def test_duplicate_payee_name_rejected(tenant_id):
    with tenant_scope(tenant_id):
        payee_service.create_payee(name="Trader Joe's")
        with pytest.raises(payee_service.PayeeError):
            payee_service.create_payee(name="TRADER JOE'S")  # normalizes to the same value


def test_get_or_create_payee_is_idempotent(tenant_id):
    with tenant_scope(tenant_id):
        p1, created1 = payee_service.get_or_create_payee(name="Whole Foods")
        p2, created2 = payee_service.get_or_create_payee(name="whole foods ")
        assert created1 is True
        assert created2 is False
        assert p1.id == p2.id


def test_payee_default_category_used_in_transaction(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _salary = _seed()
        payee = payee_service.create_payee(name="Trader Joe's", default_category=groceries)
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now(), payee=payee
        )
        assert txn.payee_id == payee.id


# --------------------------------------------------------------- tags
def test_create_tag(tenant_id):
    with tenant_scope(tenant_id):
        tag = tag_service.create_tag(name="business", color="#00ff00")
        assert tag.name == "business"


def test_duplicate_tag_rejected(tenant_id):
    with tenant_scope(tenant_id):
        tag_service.create_tag(name="business")
        with pytest.raises(tag_service.TagError):
            tag_service.create_tag(name="business")


def test_set_transaction_tags_add_and_remove(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _salary = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        biz = tag_service.create_tag(name="business")
        personal = tag_service.create_tag(name="personal")

        tag_service.set_transaction_tags(txn=txn, tags=[biz, personal])
        assert {t.tag.name for t in txn.tag_links.all()} == {"business", "personal"}

        # remove one, keep the other
        tag_service.set_transaction_tags(txn=txn, tags=[biz])
        assert {t.tag.name for t in txn.tag_links.all()} == {"business"}


def test_set_transaction_tags_is_idempotent(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _salary = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        biz = tag_service.create_tag(name="business")
        tag_service.set_transaction_tags(txn=txn, tags=[biz])
        tag_service.set_transaction_tags(txn=txn, tags=[biz])  # calling twice must not error or duplicate
        assert txn.tag_links.count() == 1


def test_tag_can_be_removed_and_readded_without_uniqueness_violation(tenant_id):
    """Regression test for the fixed TransactionTag unique constraint: it
    must be scoped to live (non-soft-deleted) rows only."""
    with tenant_scope(tenant_id):
        checking, groceries, _salary = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        biz = tag_service.create_tag(name="business")
        tag_service.set_transaction_tags(txn=txn, tags=[biz])  # add
        tag_service.set_transaction_tags(txn=txn, tags=[])  # remove (soft delete)
        tag_service.set_transaction_tags(txn=txn, tags=[biz])  # re-add: must not hit uniqueness collision
        assert txn.tag_links.count() == 1


# --------------------------------------------------------------- attachments
def test_request_attachment_upload_creates_pending_row(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _salary = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        attachment, upload_url = attachment_service.request_attachment_upload(
            txn=txn, filename="receipt.pdf", content_type="application/pdf", byte_size=1024
        )
        assert attachment.status == AttachmentStatus.PENDING
        assert attachment.transaction_id == txn.id
        assert "receipt.pdf" in attachment.storage_key
        # local FileSystemStorage in tests doesn't support presigning
        assert upload_url is None


def test_attachment_upload_url_generated_when_storage_supports_presigning(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _salary = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )

        class _FakeS3Client:
            def generate_presigned_url(self, operation, Params, ExpiresIn):
                return f"https://fake-bucket.s3.amazonaws.com/{Params['Key']}?sig=abc"

        class _FakeMeta:
            client = _FakeS3Client()

        class _FakeConnection:
            meta = _FakeMeta()

        with (
            patch("apps.common.storage.default_storage.connection", _FakeConnection(), create=True),
            patch("apps.common.storage.default_storage.bucket_name", "fake-bucket", create=True),
        ):
            attachment, upload_url = attachment_service.request_attachment_upload(
                txn=txn, filename="receipt.pdf", content_type="application/pdf", byte_size=1024
            )
        assert upload_url is not None
        assert attachment.storage_key in upload_url


def test_attachment_rejects_oversized_file(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _salary = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        with pytest.raises(attachment_service.AttachmentError):
            attachment_service.request_attachment_upload(
                txn=txn, filename="huge.mp4", content_type="video/mp4", byte_size=999_999_999
            )


def test_confirm_attachment_upload_is_idempotent(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _salary = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        attachment, _url = attachment_service.request_attachment_upload(
            txn=txn, filename="r.pdf", content_type="application/pdf", byte_size=100
        )
        confirmed = attachment_service.confirm_attachment_upload(attachment=attachment, checksum="abc123")
        assert confirmed.status == AttachmentStatus.UPLOADED
        assert confirmed.checksum == "abc123"

        # confirming again is a no-op, not an error
        confirmed_again = attachment_service.confirm_attachment_upload(
            attachment=confirmed, checksum="different"
        )
        assert confirmed_again.checksum == "abc123"  # unchanged


# --------------------------------------------------------------- transaction editing
def test_update_transaction_memo_and_payee(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _salary = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now(), memo="old"
        )
        payee = payee_service.create_payee(name="Trader Joe's")
        updated = services.update_transaction(txn=txn, payee=payee, memo="new memo")
        assert updated.memo == "new memo"
        assert updated.payee_id == payee.id
        assert updated.amount_minor == -5000  # untouched


def test_update_transaction_recategorize(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _salary = _seed()
        dining = services.create_category(name="Dining", kind=CategoryKind.EXPENSE, currency="USD")
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        updated = services.update_transaction(txn=txn, category=dining)
        assert updated.category_id == dining.id
        # ledger untouched — same balance as before
        assert selectors.account_current_balance_minor(checking) == -5000


def test_update_transaction_rejects_wrong_category_kind(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, salary = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        with pytest.raises(services.CategoryKindError):
            services.update_transaction(txn=txn, category=salary)  # income category on an expense txn


def test_update_transaction_rejects_category_on_transfer(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, salary = _seed()
        savings = services.create_financial_account(
            name="Savings", account_type=AccountType.SAVINGS, currency="USD"
        )
        services.record_income(
            financial_account=checking, category=salary, amount_minor=100000, occurred_at=_now()
        )
        out_txn, _in_txn = services.record_transfer(
            from_account=checking, to_account=savings, amount_minor=10000, occurred_at=_now()
        )
        with pytest.raises(services.CategoryKindError):
            services.update_transaction(txn=out_txn, category=groceries)


def test_update_transaction_can_clear_category(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _salary = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        updated = services.update_transaction(txn=txn, category=None)
        assert updated.category_id is None


def test_cannot_edit_voided_transaction(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _salary = _seed()
        txn = services.record_expense(
            financial_account=checking, category=groceries, amount_minor=5000, occurred_at=_now()
        )
        services.void_transaction(txn=txn)
        txn.refresh_from_db()
        with pytest.raises(services.FinanceError):
            services.update_transaction(txn=txn, memo="nope")


def test_update_transaction_omitted_fields_left_alone(tenant_id):
    with tenant_scope(tenant_id):
        checking, groceries, _salary = _seed()
        payee = payee_service.create_payee(name="Store")
        txn = services.record_expense(
            financial_account=checking,
            category=groceries,
            amount_minor=5000,
            occurred_at=_now(),
            memo="original",
            payee=payee,
        )
        # only touch memo; category/payee must be untouched
        services.update_transaction(txn=txn, memo="updated")
        txn.refresh_from_db()
        assert txn.memo == "updated"
        assert txn.category_id == groceries.id
        assert txn.payee_id == payee.id
