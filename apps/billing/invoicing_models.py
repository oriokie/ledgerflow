"""Invoicing, refunds and credits.

Why totals are stored rather than computed
------------------------------------------
The product's standing rule is "no persisted projections — read from the
ledger". An invoice is the deliberate exception, and it is not really an
exception at all: an invoice is not a *view* of current state, it is a
point-in-time legal artifact. Recomputing last March's invoice from today's
plan prices, today's tax rates and today's exchange rates would produce a
different document than the one the customer received and paid, which is the
opposite of what an invoice is for. So an invoice freezes its own arithmetic
at issue time and never recalculates.

The same reasoning does *not* apply to, say, a tenant's current balance, which
stays computed on demand.

Money is integer minor units throughout, as everywhere else in the product.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    OVERDUE = "overdue", "Overdue"
    CANCELLED = "cancelled", "Cancelled"
    REFUNDED = "refunded", "Refunded"


class InvoiceSequence(models.Model):
    """Per-year counter backing human-readable invoice numbers.

    A UUID is unusable as an invoice number — customers quote them to their
    accountants and tax authorities expect a monotonic series. Postgres
    sequences would be simpler but are non-transactional by design: a rolled
    back invoice would burn a number and leave a gap, and gaps in an invoice
    series are a question an auditor will ask.

    A counter row taken with `SELECT ... FOR UPDATE` serialises issuance
    instead. That is a deliberate throughput ceiling on invoice *creation*
    only, which is a background, once-per-tenant-per-period operation — not a
    request-path one.
    """

    year = models.PositiveSmallIntegerField(primary_key=True)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "invoice sequence"

    def __str__(self) -> str:
        return f"{self.year}: {self.last_number}"


class Invoice(UUIDModel, TimeStampedModel):
    """A bill issued to a tenant.

    Carries its own billing-address snapshot (`billing_name`, `billing_email`,
    `billing_country`) rather than joining to the tenant at render time: an
    invoice must keep showing the details that were true when it was issued,
    even after the customer moves country or changes their billing contact.
    """

    tenant_id = models.UUIDField(db_index=True)
    number = models.CharField(max_length=32, unique=True)
    subscription = models.ForeignKey(
        "billing.Subscription", null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices"
    )
    status = models.CharField(max_length=16, choices=InvoiceStatus.choices, default=InvoiceStatus.DRAFT)

    currency = models.CharField(max_length=3, default="USD")
    issue_date = models.DateField()
    due_date = models.DateField()
    paid_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)

    # Frozen arithmetic. subtotal - discount - credit + tax = total.
    subtotal_minor = models.PositiveIntegerField(default=0)
    discount_minor = models.PositiveIntegerField(default=0)
    credit_minor = models.PositiveIntegerField(default=0)
    tax_minor = models.PositiveIntegerField(default=0)
    total_minor = models.PositiveIntegerField(default=0)
    amount_paid_minor = models.PositiveIntegerField(default=0)

    tax_rate_bps = models.PositiveIntegerField(default=0)  # basis points, e.g. 2000 = 20%
    tax_label = models.CharField(max_length=40, blank=True, default="")  # "VAT", "GST", ...

    coupon = models.ForeignKey(
        "billing.Coupon", null=True, blank=True, on_delete=models.SET_NULL, related_name="invoices"
    )

    # Snapshot of who this was billed to, at issue time.
    billing_name = models.CharField(max_length=200, blank=True, default="")
    billing_email = models.EmailField(blank=True, default="")
    billing_country = models.CharField(max_length=2, blank=True, default="")

    notes = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-issue_date", "-created_at"]
        indexes = [
            models.Index(fields=["tenant_id", "-issue_date"]),
            models.Index(fields=["status", "due_date"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        return self.number

    @property
    def amount_due_minor(self) -> int:
        return max(self.total_minor - self.amount_paid_minor, 0)

    @property
    def is_settled(self) -> bool:
        return self.status in {InvoiceStatus.PAID, InvoiceStatus.CANCELLED, InvoiceStatus.REFUNDED}


class InvoiceLineItem(UUIDModel, TimeStampedModel):
    """One charge on an invoice. Also frozen — `amount_minor` is stored rather
    than derived from quantity × unit price so a later rounding-rule change
    cannot retroactively alter an issued document."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="line_items")
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)
    unit_amount_minor = models.PositiveIntegerField(default=0)
    amount_minor = models.PositiveIntegerField(default=0)
    #: Service period this line covers, for prorated or partial-period charges.
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["sort_order", "created_at"]

    def __str__(self) -> str:
        return f"{self.description} ({self.amount_minor})"


class RefundStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    APPROVED = "approved", "Approved"
    PROCESSING = "processing", "Processing"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    REJECTED = "rejected", "Rejected"


class Refund(UUIDModel, TimeStampedModel):
    """A request to return money, and its outcome.

    Modelled as a request/approval workflow rather than a single "issue
    refund" call because the platform RBAC splits `refund.request` from
    `refund.approve`. The person who tells a customer they'll be refunded is
    usually not the person authorised to move the money, and the model has to
    be able to represent the gap between those two moments — including the
    case where approval never comes (`REJECTED`).
    """

    tenant_id = models.UUIDField(db_index=True)
    payment = models.ForeignKey("billing.Payment", on_delete=models.PROTECT, related_name="refunds")
    invoice = models.ForeignKey(
        Invoice, null=True, blank=True, on_delete=models.SET_NULL, related_name="refunds"
    )

    amount_minor = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="USD")
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=RefundStatus.choices, default=RefundStatus.REQUESTED)

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="refunds_requested",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="refunds_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True, default="")

    provider = models.CharField(max_length=32, blank=True, default="")
    provider_ref = models.CharField(max_length=255, blank=True, default="")
    failure_reason = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant_id", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["provider", "provider_ref"]),
        ]

    def __str__(self) -> str:
        return f"refund {self.amount_minor} {self.currency} [{self.status}]"

    @property
    def is_open(self) -> bool:
        return self.status in {RefundStatus.REQUESTED, RefundStatus.APPROVED, RefundStatus.PROCESSING}


class CreditKind(models.TextChoices):
    GOODWILL = "goodwill", "Goodwill"
    PROMOTIONAL = "promotional", "Promotional"
    ADJUSTMENT = "adjustment", "Billing adjustment"
    REFUND_OFFSET = "refund_offset", "Refund offset"


class Credit(UUIDModel, TimeStampedModel):
    """Account credit that offsets future invoices.

    `remaining_minor` is tracked on the row rather than derived by summing
    applications. That is a considered trade: the alternative requires a join
    and an aggregate on every invoice issuance, and — more importantly — the
    remaining balance is the thing concurrent invoice runs contend over, so
    having it as a single lockable column is what makes double-spending a
    credit preventable with `SELECT ... FOR UPDATE`.
    """

    tenant_id = models.UUIDField(db_index=True)
    amount_minor = models.PositiveIntegerField()
    remaining_minor = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="USD")
    kind = models.CharField(max_length=20, choices=CreditKind.choices, default=CreditKind.GOODWILL)
    reason = models.TextField(blank=True, default="")

    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="credits_issued",
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant_id", "-created_at"]),
            # The hot path: "what credit can this invoice consume", oldest first.
            models.Index(
                fields=["tenant_id", "currency", "created_at"],
                name="billing_credit_live_idx",
                condition=models.Q(voided_at__isnull=True, remaining_minor__gt=0),
            ),
        ]

    def __str__(self) -> str:
        return f"credit {self.remaining_minor}/{self.amount_minor} {self.currency}"

    @property
    def is_live(self) -> bool:
        return self.voided_at is None and self.remaining_minor > 0


class CreditApplication(UUIDModel, TimeStampedModel):
    """Records that a specific credit paid down a specific invoice, so the
    balance is auditable rather than just a number that went down."""

    credit = models.ForeignKey(Credit, on_delete=models.CASCADE, related_name="applications")
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="credit_applications")
    amount_minor = models.PositiveIntegerField()

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["credit", "invoice"], name="uniq_credit_per_invoice"),
        ]

    def __str__(self) -> str:
        return f"{self.amount_minor} of {self.credit_id} -> {self.invoice_id}"
