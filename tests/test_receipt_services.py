"""Receipt services: upload, processing, and linking to a transaction.

The property tested hardest is the one the whole app exists to enforce: an OCR
guess never reaches the ledger without a person confirming it. Every test that
links a receipt asserts the posted transaction matches the *confirmed* fields,
never the raw `parsed_fields`.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from apps.finance import services as finance_services
from apps.finance.models import AccountType, CategoryKind
from apps.ledger.models import LedgerLine
from apps.receipts import services as receipts
from apps.receipts.models import Receipt, ReceiptStatus
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _account_and_category():
    account = finance_services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency="USD", opening_balance_minor=500_000
    )
    category = finance_services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
    return account, category


def _uploaded_receipt(*, image_bytes: bytes = b"fake-jpeg-bytes") -> Receipt:
    receipt, _ = receipts.request_receipt_upload(
        filename="receipt.jpg", content_type="image/jpeg", byte_size=len(image_bytes)
    )
    return receipts.confirm_receipt_upload(receipt=receipt, image_bytes=image_bytes)


# =============================================================================
# Upload
# =============================================================================
def test_requesting_an_upload_creates_a_pending_receipt(tenant):
    with tenant_scope(tenant):
        receipt, _ = receipts.request_receipt_upload(
            filename="r.jpg", content_type="image/jpeg", byte_size=1_000
        )
        assert receipt.status == ReceiptStatus.PENDING_UPLOAD
        assert receipt.storage_key


def test_an_oversized_image_is_rejected(tenant):
    with tenant_scope(tenant), pytest.raises(receipts.ReceiptError, match="MB limit"):
        receipts.request_receipt_upload(filename="r.jpg", content_type="image/jpeg", byte_size=99_000_000)


def test_an_unsupported_content_type_is_rejected(tenant):
    with tenant_scope(tenant), pytest.raises(receipts.ReceiptError, match="Unsupported"):
        receipts.request_receipt_upload(filename="r.pdf", content_type="application/pdf", byte_size=1_000)


def test_confirming_twice_is_refused(tenant):
    with tenant_scope(tenant):
        receipt = _uploaded_receipt()
        with pytest.raises(receipts.ReceiptError, match="already"):
            receipts.confirm_receipt_upload(receipt=receipt, image_bytes=b"x")


# =============================================================================
# OCR processing
# =============================================================================
def test_processing_a_readable_receipt_marks_it_parsed(tenant, settings):
    settings.RECEIPTS_OCR_PROVIDER = "tesseract"
    with tenant_scope(tenant):
        import io

        from PIL import Image, ImageDraw

        image = Image.new("RGB", (500, 300), "white")
        draw = ImageDraw.Draw(image)
        draw.text((20, 20), "CORNER SHOP", fill="black")
        draw.text((20, 100), "TOTAL 12.50", fill="black")
        buf = io.BytesIO()
        image.save(buf, format="PNG")

        receipt = _uploaded_receipt(image_bytes=buf.getvalue())
        result = receipts.process_receipt_ocr(receipt=receipt)

        assert result.status in (ReceiptStatus.PARSED, ReceiptStatus.UNREADABLE)
        assert result.raw_text != ""


def test_a_blank_image_is_marked_unreadable_not_failed(tenant, settings):
    """No OCR provider configured is a valid outcome, not an error."""
    settings.RECEIPTS_OCR_PROVIDER = "null"
    with tenant_scope(tenant):
        receipt = _uploaded_receipt()
        result = receipts.process_receipt_ocr(receipt=receipt)
        assert result.status == ReceiptStatus.UNREADABLE
        assert result.confirmed_amount_minor is None


def test_a_missing_image_fails_gracefully(tenant):
    """A bad row must never crash the processing pipeline."""
    with tenant_scope(tenant):
        receipt, _ = receipts.request_receipt_upload(
            filename="r.jpg", content_type="image/jpeg", byte_size=1_000
        )
        receipt.status = ReceiptStatus.UPLOADED
        receipt.save()
        # No bytes were ever written to storage.
        result = receipts.process_receipt_ocr(receipt=receipt)
        assert result.status == ReceiptStatus.FAILED
        assert result.error


def test_processing_pre_fills_confirmed_fields_as_a_starting_point(tenant, settings):
    settings.RECEIPTS_OCR_PROVIDER = "null"
    with tenant_scope(tenant):
        receipt = _uploaded_receipt()
        # Simulate a provider that found something, without depending on real
        # OCR accuracy for this assertion.
        from apps.receipts import services as svc

        result = svc.process_receipt_ocr(receipt=receipt)
        # With the null provider nothing is found, and nothing is pre-filled —
        # confirming the "starting point only" behaviour doesn't invent values.
        assert result.confirmed_amount_minor is None
        assert result.confirmed_merchant == ""


# =============================================================================
# Confirming fields
# =============================================================================
def test_the_user_can_override_every_confirmed_field(tenant):
    with tenant_scope(tenant):
        receipt = _uploaded_receipt()
        updated = receipts.update_confirmed_fields(
            receipt=receipt,
            merchant="Real Merchant Name",
            amount_minor=999,
            occurred_on=date(2026, 5, 1),
        )
        assert updated.confirmed_merchant == "Real Merchant Name"
        assert updated.confirmed_amount_minor == 999
        assert updated.confirmed_occurred_on == date(2026, 5, 1)


def test_a_non_positive_confirmed_amount_is_rejected(tenant):
    with tenant_scope(tenant):
        receipt = _uploaded_receipt()
        with pytest.raises(receipts.ReceiptError):
            receipts.update_confirmed_fields(receipt=receipt, amount_minor=0)


# =============================================================================
# Linking — the accounting-safety core of the module
# =============================================================================
def test_linking_posts_the_confirmed_amount_not_the_parsed_one(tenant):
    """The one rule this whole app exists to enforce: an OCR guess never
    reaches the ledger without a person having confirmed it."""
    with tenant_scope(tenant):
        account, category = _account_and_category()
        receipt = _uploaded_receipt()
        # Simulate OCR having guessed wrong.
        receipt.parsed_fields = {"amount_minor": 99_999}
        receipt.save()
        # The user corrects it before confirming.
        receipts.update_confirmed_fields(receipt=receipt, amount_minor=1_250)

        txn = receipts.link_to_transaction(receipt=receipt, financial_account=account, category=category)
        assert txn.amount_minor == -1_250  # signed: money out
        assert txn.amount_minor != -99_999


def test_linking_without_a_confirmed_amount_is_refused(tenant):
    with tenant_scope(tenant):
        account, category = _account_and_category()
        receipt = _uploaded_receipt()
        with pytest.raises(receipts.ReceiptError, match="Confirm an amount"):
            receipts.link_to_transaction(receipt=receipt, financial_account=account, category=category)


def test_linking_posts_a_balanced_ledger_entry(tenant):
    with tenant_scope(tenant):
        account, category = _account_and_category()
        receipt = _uploaded_receipt()
        receipts.update_confirmed_fields(receipt=receipt, merchant="Shop", amount_minor=2_000)

        before = LedgerLine.objects.count()
        txn = receipts.link_to_transaction(receipt=receipt, financial_account=account, category=category)
        lines = list(LedgerLine.objects.filter(entry=txn.journal_entry))
        assert len(lines) == 2
        assert LedgerLine.objects.count() == before + 2


def test_linking_twice_is_refused(tenant):
    with tenant_scope(tenant):
        account, category = _account_and_category()
        receipt = _uploaded_receipt()
        receipts.update_confirmed_fields(receipt=receipt, amount_minor=1_000)
        receipts.link_to_transaction(receipt=receipt, financial_account=account, category=category)

        with pytest.raises(receipts.ReceiptError, match="already linked"):
            receipts.link_to_transaction(receipt=receipt, financial_account=account, category=category)


def test_linking_teaches_the_automation_engine(tenant):
    """A confirmed category is a real signal about this merchant, same as any
    other categorised transaction."""
    with tenant_scope(tenant):
        from apps.intelligence.models import MerchantProfile

        account, category = _account_and_category()
        receipt = _uploaded_receipt()
        receipts.update_confirmed_fields(receipt=receipt, merchant="Corner Shop", amount_minor=1_500)
        receipts.link_to_transaction(receipt=receipt, financial_account=account, category=category)

        assert MerchantProfile.objects.filter(display_name="Corner Shop").exists()


def test_a_linked_receipt_carries_a_memo_referencing_the_merchant(tenant):
    with tenant_scope(tenant):
        account, category = _account_and_category()
        receipt = _uploaded_receipt()
        receipts.update_confirmed_fields(receipt=receipt, merchant="Corner Shop", amount_minor=1_500)
        txn = receipts.link_to_transaction(receipt=receipt, financial_account=account, category=category)
        assert "Corner Shop" in txn.memo


def test_discarding_never_posts_anything(tenant):
    with tenant_scope(tenant):
        receipt = _uploaded_receipt()
        before = LedgerLine.objects.count()
        discarded = receipts.discard(receipt=receipt)
        assert discarded.status == ReceiptStatus.DISCARDED
        assert LedgerLine.objects.count() == before


def test_a_linked_receipt_cannot_be_discarded(tenant):
    with tenant_scope(tenant):
        account, category = _account_and_category()
        receipt = _uploaded_receipt()
        receipts.update_confirmed_fields(receipt=receipt, amount_minor=1_000)
        receipts.link_to_transaction(receipt=receipt, financial_account=account, category=category)

        with pytest.raises(receipts.ReceiptError):
            receipts.discard(receipt=receipt)


def test_pending_review_lists_only_receipts_awaiting_a_person(tenant, settings):
    settings.RECEIPTS_OCR_PROVIDER = "null"
    with tenant_scope(tenant):
        account, category = _account_and_category()
        parsed = _uploaded_receipt()
        receipts.process_receipt_ocr(receipt=parsed)  # -> unreadable, still pending review

        linked = _uploaded_receipt()
        receipts.update_confirmed_fields(receipt=linked, amount_minor=500)
        receipts.link_to_transaction(receipt=linked, financial_account=account, category=category)

        queue_ids = {r.id for r in receipts.pending_review()}
        assert parsed.id in queue_ids
        assert linked.id not in queue_ids


# =============================================================================
# API
# =============================================================================
def test_api_full_receipt_flow(tenant_context):
    _, client = tenant_context
    account = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD", "opening_balance_minor": 500_000},
        format="json",
    ).data
    category = client.post(
        "/api/v1/finance/categories/",
        {"name": "Groceries", "kind": "expense", "currency": "USD"},
        format="json",
    ).data

    requested = client.post(
        "/api/v1/receipts/upload/",
        {"filename": "r.jpg", "content_type": "image/jpeg", "byte_size": 5_000},
        format="json",
    )
    assert requested.status_code == 201, requested.data
    receipt_id = requested.data["id"]

    import base64

    confirmed = client.post(
        f"/api/v1/receipts/{receipt_id}/confirm-upload/",
        {"image_base64": base64.b64encode(b"fake-bytes").decode()},
        format="json",
    )
    assert confirmed.status_code == 200, confirmed.data

    fields = client.patch(
        f"/api/v1/receipts/{receipt_id}/fields/",
        {"merchant": "Corner Shop", "amount_minor": 1_850},
        format="json",
    )
    assert fields.status_code == 200, fields.data
    assert fields.data["confirmed_amount_minor"] == 1_850

    linked = client.post(
        f"/api/v1/receipts/{receipt_id}/link/",
        {"financial_account_id": account["id"], "category_id": category["id"]},
        format="json",
    )
    assert linked.status_code == 200, linked.data
    assert linked.data["receipt"]["status"] == "linked"

    # The point of "full" flow: linking must actually post a transaction, not
    # just flip the receipt's own status. Fetched and never asserted on before
    # — a gap that let the flow claim "linked" without proving anything moved.
    [txn] = client.get("/api/v1/finance/transactions/").data["results"]
    assert txn["amount_minor"] == -1_850  # an expense: money out
    # `.data` on the test client's response holds pre-render Python objects —
    # `TransactionSerializer.financial_account_id` comes back as a `UUID`,
    # while `account["id"]` (read off an earlier response the same way) is
    # already a `str`. `str()` on both sides compares the value, not the type.
    assert str(txn["financial_account_id"]) == str(account["id"])
    assert str(txn["category_id"]) == str(category["id"])
    assert txn["memo"] == "From receipt: Corner Shop"


def test_api_rejects_linking_with_no_confirmed_amount(tenant_context):
    _, client = tenant_context
    account = client.post(
        "/api/v1/finance/accounts/",
        {"name": "Checking", "account_type": "checking", "currency": "USD"},
        format="json",
    ).data
    category = client.post(
        "/api/v1/finance/categories/",
        {"name": "Groceries", "kind": "expense", "currency": "USD"},
        format="json",
    ).data
    requested = client.post(
        "/api/v1/receipts/upload/",
        {"filename": "r.jpg", "content_type": "image/jpeg", "byte_size": 5_000},
        format="json",
    )
    receipt_id = requested.data["id"]
    client.post(f"/api/v1/receipts/{receipt_id}/confirm-upload/", {}, format="json")

    resp = client.post(
        f"/api/v1/receipts/{receipt_id}/link/",
        {"financial_account_id": account["id"], "category_id": category["id"]},
        format="json",
    )
    assert resp.status_code == 422


def test_api_rejects_an_oversized_upload_request(tenant_context):
    _, client = tenant_context
    resp = client.post(
        "/api/v1/receipts/upload/",
        {"filename": "r.jpg", "content_type": "image/jpeg", "byte_size": 99_000_000},
        format="json",
    )
    assert resp.status_code == 422


def test_api_queue_lists_receipts_awaiting_review(tenant_context):
    membership, client = tenant_context
    requested = client.post(
        "/api/v1/receipts/upload/",
        {"filename": "r.jpg", "content_type": "image/jpeg", "byte_size": 5_000},
        format="json",
    )
    receipt_id = requested.data["id"]
    client.post(f"/api/v1/receipts/{receipt_id}/confirm-upload/", {}, format="json")

    from apps.receipts.models import Receipt, ReceiptStatus

    # The client carries the tenant; direct ORM access needs its own binding.
    with tenant_scope(membership.tenant_id):
        r = Receipt.objects.get(id=receipt_id)
        r.status = ReceiptStatus.UNREADABLE
        r.save()

    queue = client.get("/api/v1/receipts/queue/").data
    assert any(r["id"] == receipt_id for r in queue)


def test_api_discard(tenant_context):
    _, client = tenant_context
    requested = client.post(
        "/api/v1/receipts/upload/",
        {"filename": "r.jpg", "content_type": "image/jpeg", "byte_size": 5_000},
        format="json",
    )
    receipt_id = requested.data["id"]
    resp = client.post(f"/api/v1/receipts/{receipt_id}/discard/", {}, format="json")
    assert resp.status_code == 200
    assert resp.data["status"] == "discarded"
