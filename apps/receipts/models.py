"""Receipt scanning — an image, what OCR read from it, and what a person
confirmed.

Three states a receipt can be in, and the model keeps them visually distinct
because they carry very different trust levels:

    raw text        what the OCR engine literally read — noisy, unreviewed
    parsed fields    what a heuristic pulled out of that text — a guess
    confirmed fields  what the user actually approved

Only `confirmed_*` fields ever reach a transaction. OCR on a receipt photo is
wrong often enough — a smudged total, a misread date — that auto-posting from
it would put fabricated numbers in the ledger. The same discipline the rest of
the product applies to AI-authored insights applies here: the engine proposes,
a person disposes.

Upload follows the existing presigned two-step pattern (`apps/common/storage.py`,
mirrored from `apps/finance/attachments.py`): the app server never sees the
image bytes for the PUT itself, only a confirmation afterward.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import SoftDeletableModel


class ReceiptStatus(models.TextChoices):
    #: Presigned URL issued, image not yet confirmed uploaded.
    PENDING_UPLOAD = "pending_upload", "Awaiting upload"
    UPLOADED = "uploaded", "Uploaded"
    PROCESSING = "processing", "Reading receipt"
    PARSED = "parsed", "Ready for review"
    #: OCR ran but extracted nothing usable — still a valid state, not an error.
    UNREADABLE = "unreadable", "Couldn't read this one"
    FAILED = "failed", "Processing failed"
    #: Confirmed and turned into a transaction.
    LINKED = "linked", "Added to your transactions"
    DISCARDED = "discarded", "Discarded"


class Receipt(SoftDeletableModel):
    financial_account = models.ForeignKey(
        "finance.FinancialAccount", null=True, blank=True, on_delete=models.SET_NULL, related_name="receipts"
    )
    status = models.CharField(
        max_length=16, choices=ReceiptStatus.choices, default=ReceiptStatus.PENDING_UPLOAD
    )

    # --- storage ---
    storage_key = models.CharField(max_length=512)
    content_type = models.CharField(max_length=100, blank=True, default="")
    byte_size = models.PositiveIntegerField(default=0)

    # --- what OCR read, unreviewed ---
    raw_text = models.TextField(blank=True, default="")
    #: Structured guesses: {"merchant": ..., "amount_minor": ..., "occurred_on": ...,
    #: "line_items": [...]}. Never trusted directly — see the module docstring.
    parsed_fields = models.JSONField(default=dict, blank=True)
    #: 0-1, the provider's own estimate of how much to trust `parsed_fields`.
    confidence = models.FloatField(default=0.0)
    provider = models.CharField(max_length=64, blank=True, default="")
    error = models.CharField(max_length=255, blank=True, default="")

    # --- what the user confirmed ---
    confirmed_merchant = models.CharField(max_length=160, blank=True, default="")
    confirmed_amount_minor = models.BigIntegerField(null=True, blank=True)
    confirmed_occurred_on = models.DateField(null=True, blank=True)
    confirmed_category = models.ForeignKey(
        "finance.Category", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    linked_transaction = models.OneToOneField(
        "finance.Transaction", null=True, blank=True, on_delete=models.SET_NULL, related_name="receipt"
    )

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="receipt_status_idx"),
            models.Index(fields=["tenant_id", "-created_at"], name="receipt_recent_idx"),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Receipt {self.id} ({self.status})"

    @property
    def is_ready_for_review(self) -> bool:
        return self.status in (ReceiptStatus.PARSED, ReceiptStatus.UNREADABLE)
