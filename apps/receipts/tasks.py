"""Async receipt processing.

OCR is slow enough (hundreds of milliseconds to a few seconds per image) that
running it inline on the upload-confirm request would make "add a receipt"
feel broken on a phone with a weak connection. This is the one-line Celery
wrapper around the synchronous, directly-testable `process_receipt_ocr`.
"""

from __future__ import annotations

import logging
import uuid

from celery import shared_task

from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant

logger = logging.getLogger("ledgerflow.receipts")


@shared_task(
    name="receipts.process_receipt",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def process_receipt(self, receipt_id: str) -> None:
    from .models import Receipt
    from .services import process_receipt_ocr

    try:
        # The receipt's tenant isn't known until the row is read, so this task
        # binds to itself rather than being called with a tenant argument —
        # the same pattern as the debt and goal auto-contribution tasks.
        rid = uuid.UUID(str(receipt_id))
        receipt = Receipt.unscoped.filter(id=rid).first()
        if receipt is None:
            return
        bind_db_tenant(receipt.tenant_id)
        with use_tenant(receipt.tenant_id):
            receipt = Receipt.objects.get(id=rid)
            process_receipt_ocr(receipt=receipt)
    except Exception as exc:
        logger.exception("receipt processing failed for %s", receipt_id)
        raise self.retry(exc=exc) from exc
