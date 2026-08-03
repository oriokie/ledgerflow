"""Receipt services — upload, OCR processing, and turning a receipt into a
transaction.

Follows the attachment app's two-step presigned upload exactly
(`apps/finance/attachments.py`): the app server never sees image bytes for the
PUT itself, only a confirmation afterward that triggers async processing.

The governing rule, same as the automation engine: **OCR proposes, a person
disposes.** `parsed_fields` is never posted to the ledger directly. Turning a
receipt into a transaction is `link_to_transaction`, a distinct, explicit step
that always uses the *confirmed* fields — what the user actually approved,
which may differ from what OCR read.
"""

from __future__ import annotations

import uuid
from datetime import date

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from apps.common.storage import generate_presigned_download_url, generate_presigned_upload_url
from apps.finance.models import Category, FinancialAccount, Transaction
from apps.finance.payees import get_or_create_payee

from .models import Receipt, ReceiptStatus

_MAX_BYTES = 15 * 1024 * 1024  # a phone photo, not a video
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}


class ReceiptError(Exception): ...


def _storage_key(*, tenant_id, receipt_id, filename: str) -> str:
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"receipts/{tenant_id}/{receipt_id}/{uuid.uuid4()}-{safe_name}"


@transaction.atomic
def request_receipt_upload(
    *,
    filename: str,
    content_type: str,
    byte_size: int,
    financial_account: FinancialAccount | None = None,
) -> tuple[Receipt, str | None]:
    """Create a pending Receipt and return (receipt, presigned_upload_url).

    `upload_url` is `None` when the active storage backend can't presign
    (local dev) — callers fall back to a direct-write path, same convention as
    attachments.
    """
    if byte_size <= 0:
        raise ReceiptError("byte_size must be positive.")
    if byte_size > _MAX_BYTES:
        raise ReceiptError(f"Receipt image exceeds the {_MAX_BYTES // (1024 * 1024)}MB limit.")
    if content_type not in _ALLOWED_TYPES:
        raise ReceiptError(f"Unsupported image type {content_type!r}.")

    receipt = Receipt.objects.create(
        financial_account=financial_account,
        status=ReceiptStatus.PENDING_UPLOAD,
        content_type=content_type,
        byte_size=byte_size,
    )
    key = _storage_key(tenant_id=receipt.tenant_id, receipt_id=receipt.id, filename=filename)
    receipt.storage_key = key
    receipt.save(update_fields=["storage_key", "updated_at"])

    upload_url = generate_presigned_upload_url(key=key, content_type=content_type)
    return receipt, upload_url


@transaction.atomic
def confirm_receipt_upload(*, receipt: Receipt, image_bytes: bytes | None = None) -> Receipt:
    """Mark a receipt uploaded and queue OCR processing.

    `image_bytes` is only used in environments without presigning (local dev,
    where the client can't PUT straight to S3): the server writes the bytes
    itself rather than leaving the receipt stuck in `PENDING_UPLOAD` forever.
    """
    if receipt.status != ReceiptStatus.PENDING_UPLOAD:
        raise ReceiptError("This receipt has already been confirmed.")

    if image_bytes is not None:
        default_storage.save(receipt.storage_key, ContentFile(image_bytes))

    receipt.status = ReceiptStatus.UPLOADED
    receipt.save(update_fields=["status", "updated_at"])

    from .tasks import process_receipt

    transaction.on_commit(lambda: process_receipt.delay(str(receipt.id)))
    return receipt


@transaction.atomic
def process_receipt_ocr(*, receipt: Receipt) -> Receipt:
    """Run OCR and store the raw text plus a parsed guess.

    Synchronous; the async wrapper lives in `tasks.py` so this stays directly
    testable without Celery. Never raises out to the caller — a bad image is a
    receipt in `UNREADABLE` or `FAILED`, not a crashed pipeline, because a
    single unreadable photo must never take down the processing queue.
    """
    from .providers import get_ocr_provider

    if receipt.status not in (ReceiptStatus.UPLOADED, ReceiptStatus.FAILED):
        return receipt

    receipt.status = ReceiptStatus.PROCESSING
    receipt.save(update_fields=["status", "updated_at"])

    try:
        image_bytes = default_storage.open(receipt.storage_key).read()
    except FileNotFoundError:
        receipt.status = ReceiptStatus.FAILED
        receipt.error = "Image not found in storage."
        receipt.save(update_fields=["status", "error", "updated_at"])
        return receipt

    try:
        provider = get_ocr_provider()
        result = provider.read(image_bytes, content_type=receipt.content_type)
    except Exception as exc:  # pragma: no cover - defensive; providers already guard internally
        receipt.status = ReceiptStatus.FAILED
        receipt.error = str(exc)[:255]
        receipt.save(update_fields=["status", "error", "updated_at"])
        return receipt

    receipt.raw_text = result.raw_text
    receipt.provider = result.provider
    receipt.confidence = result.extraction.confidence
    receipt.parsed_fields = {
        "merchant": result.extraction.merchant,
        "amount_minor": result.extraction.amount_minor,
        "occurred_on": (
            result.extraction.occurred_on.isoformat() if result.extraction.occurred_on else None
        ),
    }
    # Pre-fill the confirmed fields from what OCR found, as a starting point
    # only — the user can change every one of them before anything posts.
    if result.extraction.merchant:
        receipt.confirmed_merchant = result.extraction.merchant
    if result.extraction.amount_minor:
        receipt.confirmed_amount_minor = result.extraction.amount_minor
    if result.extraction.occurred_on:
        receipt.confirmed_occurred_on = result.extraction.occurred_on

    receipt.status = (
        ReceiptStatus.PARSED if result.raw_text.strip() else ReceiptStatus.UNREADABLE
    )
    receipt.save()
    return receipt


@transaction.atomic
def update_confirmed_fields(
    *,
    receipt: Receipt,
    merchant: str | None = None,
    amount_minor: int | None = None,
    occurred_on: date | None = None,
    category: Category | None = None,
) -> Receipt:
    """Record what the user actually approved, overwriting whatever OCR
    guessed. This is the only path that changes what a link will post."""
    if receipt.status == ReceiptStatus.LINKED:
        raise ReceiptError("This receipt is already linked to a transaction.")

    if merchant is not None:
        receipt.confirmed_merchant = merchant
    if amount_minor is not None:
        if amount_minor <= 0:
            raise ReceiptError("Amount must be positive.")
        receipt.confirmed_amount_minor = amount_minor
    if occurred_on is not None:
        receipt.confirmed_occurred_on = occurred_on
    if category is not None:
        receipt.confirmed_category = category

    receipt.save()
    return receipt


@transaction.atomic
def link_to_transaction(
    *, receipt: Receipt, financial_account: FinancialAccount, category: Category
) -> Transaction:
    """Turn a receipt into a real expense transaction.

    Uses only the **confirmed** fields — never `parsed_fields` directly. That
    is the one rule this whole app exists to enforce: an OCR guess never
    reaches the ledger without a person having looked at it.
    """
    from apps.finance import services as finance_services

    if receipt.status == ReceiptStatus.LINKED:
        raise ReceiptError("This receipt is already linked to a transaction.")
    if not receipt.confirmed_amount_minor:
        raise ReceiptError("Confirm an amount before linking this receipt.")

    occurred_on = receipt.confirmed_occurred_on or timezone.localdate()
    occurred_at = timezone.make_aware(
        timezone.datetime.combine(occurred_on, timezone.datetime.min.time())
    )

    payee = None
    if receipt.confirmed_merchant:
        payee, _ = get_or_create_payee(name=receipt.confirmed_merchant)

    txn = finance_services.record_expense(
        financial_account=financial_account,
        category=category,
        amount_minor=receipt.confirmed_amount_minor,
        occurred_at=occurred_at,
        memo=f"From receipt: {receipt.confirmed_merchant}" if receipt.confirmed_merchant else "",
        payee=payee,
    )

    receipt.linked_transaction = txn
    receipt.financial_account = financial_account
    receipt.confirmed_category = category
    receipt.status = ReceiptStatus.LINKED
    receipt.save()

    # A confirmed category is a real signal about this merchant — feed it to
    # the automation engine's learning store, same as any other categorised
    # transaction.
    from apps.intelligence.automation_services import learn_from_transaction

    learn_from_transaction(txn)

    return txn


def discard(*, receipt: Receipt) -> Receipt:
    if receipt.status == ReceiptStatus.LINKED:
        raise ReceiptError("Can't discard a receipt already linked to a transaction.")
    receipt.status = ReceiptStatus.DISCARDED
    receipt.save(update_fields=["status", "updated_at"])
    return receipt


def download_url(receipt: Receipt) -> str | None:
    return generate_presigned_download_url(key=receipt.storage_key)


def pending_review(*, limit: int | None = None):
    """Receipts waiting for a person to look at them."""
    qs = Receipt.objects.filter(
        status__in=[ReceiptStatus.PARSED, ReceiptStatus.UNREADABLE]
    ).order_by("-created_at")
    return qs[:limit] if limit else qs
