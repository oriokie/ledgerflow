"""Invoice lifecycle and account credit.

Sits beside `services.py` rather than inside it: subscription mechanics and
document issuance are different concerns with different change rates, and
`services.py` is already the size where adding a second domain to it would
make both harder to find.

State machine
-------------
    DRAFT ──issue──> PENDING ──payment──> PAID
      │                 │
      │                 ├──due date passes──> OVERDUE ──payment──> PAID
      │                 │
      └──void───────────┴──> CANCELLED

    PAID ──refund in full──> REFUNDED

A DRAFT invoice is editable; everything after it is not. That boundary is
where the document stops being a working total and starts being a claim on a
customer, and it is enforced in the service rather than by convention.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from .invoicing_models import (
    Credit,
    CreditApplication,
    CreditKind,
    Invoice,
    InvoiceLineItem,
    InvoiceSequence,
    InvoiceStatus,
)
from .models import Payment, PaymentStatus, Plan, Subscription

logger = logging.getLogger("ledgerflow.billing.invoicing")

#: Days from issue to due, unless a caller overrides. Net-14 rather than
#: net-30: this is self-serve SaaS collected by card, where the invoice is a
#: receipt-shaped artifact rather than a genuine credit term.
DEFAULT_PAYMENT_TERMS_DAYS = 14


class InvoicingError(Exception):
    """Raised for invoice operations that are invalid in the current state."""


@dataclass(frozen=True)
class LineItemSpec:
    """Input shape for a line. Separate from the model so callers can compose
    an invoice without touching the ORM, and so a line can be validated before
    any row exists."""

    description: str
    amount_minor: int
    quantity: int = 1
    unit_amount_minor: int | None = None
    period_start: date | None = None
    period_end: date | None = None
    metadata: dict | None = None


# --------------------------------------------------------------------- numbers
def next_invoice_number(*, year: int | None = None) -> str:
    """Allocate the next invoice number for `year`, e.g. ``INV-2026-000042``.

    Takes a row lock, so concurrent issuance serialises here rather than
    producing a duplicate number and tripping the unique constraint at commit.
    Must be called inside a transaction; every caller in this module already is.
    """
    year = year or timezone.now().year
    seq, _ = InvoiceSequence.objects.get_or_create(year=year)
    seq = InvoiceSequence.objects.select_for_update().get(pk=seq.pk)
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    return f"INV-{year}-{seq.last_number:06d}"


# --------------------------------------------------------------------- drafting
@transaction.atomic
def create_invoice(
    *,
    tenant_id,
    currency: str,
    line_items: list[LineItemSpec],
    subscription: Subscription | None = None,
    issue_date: date | None = None,
    due_date: date | None = None,
    tax_rate_bps: int = 0,
    tax_label: str = "",
    coupon=None,
    discount_minor: int = 0,
    billing_name: str = "",
    billing_email: str = "",
    billing_country: str = "",
    notes: str = "",
    apply_credit: bool = True,
    status: str = InvoiceStatus.DRAFT,
) -> Invoice:
    """Build an invoice and freeze its arithmetic.

    Order of operations matters and is the same order tax authorities expect:
    subtotal, then discount, then credit, then tax on what remains. Taxing
    before discounting would overcharge; crediting before discounting would
    consume more of a customer's credit balance than the invoice actually needs.
    """
    if not line_items:
        raise InvoicingError("An invoice needs at least one line item.")

    currency = currency.upper()
    issue_date = issue_date or timezone.now().date()
    due_date = due_date or (issue_date + timedelta(days=DEFAULT_PAYMENT_TERMS_DAYS))
    if due_date < issue_date:
        raise InvoicingError("An invoice cannot be due before it is issued.")

    subtotal = sum(max(int(li.amount_minor), 0) for li in line_items)
    discount = min(max(int(discount_minor), 0), subtotal)
    after_discount = subtotal - discount

    invoice = Invoice.objects.create(
        tenant_id=tenant_id,
        number=next_invoice_number(year=issue_date.year),
        subscription=subscription,
        status=status,
        currency=currency,
        issue_date=issue_date,
        due_date=due_date,
        subtotal_minor=subtotal,
        discount_minor=discount,
        tax_rate_bps=max(int(tax_rate_bps), 0),
        tax_label=tax_label,
        coupon=coupon,
        billing_name=billing_name,
        billing_email=billing_email,
        billing_country=(billing_country or "").upper()[:2],
        notes=notes,
        # Filled in below once credit and tax are known.
        credit_minor=0,
        tax_minor=0,
        total_minor=after_discount,
    )

    for index, spec in enumerate(line_items):
        InvoiceLineItem.objects.create(
            invoice=invoice,
            description=spec.description[:255],
            quantity=max(int(spec.quantity), 1),
            unit_amount_minor=(
                spec.unit_amount_minor
                if spec.unit_amount_minor is not None
                else int(spec.amount_minor) // max(int(spec.quantity), 1)
            ),
            amount_minor=max(int(spec.amount_minor), 0),
            period_start=spec.period_start,
            period_end=spec.period_end,
            sort_order=index,
            metadata=spec.metadata or {},
        )

    credit_used = 0
    if apply_credit and after_discount > 0:
        credit_used = _consume_credit(invoice=invoice, amount_minor=after_discount)

    taxable = after_discount - credit_used
    tax = round(taxable * invoice.tax_rate_bps / 10_000) if invoice.tax_rate_bps else 0

    invoice.credit_minor = credit_used
    invoice.tax_minor = tax
    invoice.total_minor = taxable + tax
    invoice.save(update_fields=["credit_minor", "tax_minor", "total_minor", "updated_at"])

    # A fully credited invoice has nothing to collect. Leaving it PENDING would
    # put a zero-value row in the dunning queue and email the customer about a
    # bill for nothing.
    if invoice.total_minor == 0 and invoice.status != InvoiceStatus.DRAFT:
        mark_paid(invoice=invoice, amount_minor=0)

    return invoice


def _consume_credit(*, invoice: Invoice, amount_minor: int) -> int:
    """Spend available credit against an invoice, oldest first.

    Oldest-first because credits can expire, and spending a credit that is
    about to lapse before one that is not is strictly better for the customer.

    Rows are locked for update so two invoice runs for the same tenant cannot
    both read the same `remaining_minor` and each spend it.
    """
    now = timezone.now()
    live = (
        Credit.objects.select_for_update()
        .filter(
            tenant_id=invoice.tenant_id,
            currency=invoice.currency,
            voided_at__isnull=True,
            remaining_minor__gt=0,
        )
        .exclude(expires_at__lt=now)
        .order_by("created_at")
    )

    remaining_need = amount_minor
    total_used = 0
    for credit in live:
        if remaining_need <= 0:
            break
        take = min(credit.remaining_minor, remaining_need)
        credit.remaining_minor -= take
        credit.save(update_fields=["remaining_minor", "updated_at"])
        CreditApplication.objects.create(credit=credit, invoice=invoice, amount_minor=take)
        remaining_need -= take
        total_used += take
    return total_used


# --------------------------------------------------------------------- lifecycle
@transaction.atomic
def issue_invoice(*, invoice: Invoice) -> Invoice:
    """Move a DRAFT to PENDING. The point of no return for edits."""
    if invoice.status != InvoiceStatus.DRAFT:
        raise InvoicingError(f"Only a draft invoice can be issued (this one is {invoice.status}).")
    invoice.status = InvoiceStatus.PENDING
    invoice.save(update_fields=["status", "updated_at"])
    if invoice.total_minor == 0:
        mark_paid(invoice=invoice, amount_minor=0)
    return invoice


@transaction.atomic
def mark_paid(*, invoice: Invoice, amount_minor: int | None = None, payment: Payment | None = None) -> Invoice:
    """Record settlement. Partial payments accumulate and leave the invoice open.

    A partial payment does *not* flip the status: an invoice with 40% paid is
    still owed, and treating it as PAID would drop it out of collections.
    """
    if invoice.status in {InvoiceStatus.CANCELLED, InvoiceStatus.REFUNDED}:
        raise InvoicingError(f"A {invoice.status} invoice cannot be paid.")

    paid = invoice.total_minor if amount_minor is None else max(int(amount_minor), 0)
    invoice.amount_paid_minor = min(invoice.amount_paid_minor + paid, invoice.total_minor)

    fields = ["amount_paid_minor", "updated_at"]
    if invoice.amount_paid_minor >= invoice.total_minor:
        invoice.status = InvoiceStatus.PAID
        invoice.paid_at = timezone.now()
        fields += ["status", "paid_at"]
    invoice.save(update_fields=fields)

    if payment is not None:
        metadata = dict(payment.metadata or {})
        metadata["invoice_id"] = str(invoice.id)
        metadata["invoice_number"] = invoice.number
        payment.metadata = metadata
        payment.save(update_fields=["metadata", "updated_at"])
    return invoice


@transaction.atomic
def void_invoice(*, invoice: Invoice, reason: str = "") -> Invoice:
    """Cancel an unpaid invoice and return any credit it consumed.

    Returning the credit is the part that is easy to forget and expensive to
    get wrong: a voided invoice that keeps the customer's credit has quietly
    taken money from them for a bill that no longer exists.
    """
    if invoice.status == InvoiceStatus.PAID:
        raise InvoicingError("A paid invoice cannot be voided; refund it instead.")
    if invoice.status == InvoiceStatus.CANCELLED:
        return invoice

    for application in invoice.credit_applications.select_related("credit"):
        credit = Credit.objects.select_for_update().get(pk=application.credit_id)
        credit.remaining_minor += application.amount_minor
        credit.save(update_fields=["remaining_minor", "updated_at"])
        application.delete()

    invoice.status = InvoiceStatus.CANCELLED
    invoice.voided_at = timezone.now()
    invoice.credit_minor = 0
    if reason:
        invoice.notes = (invoice.notes + f"\nVoided: {reason}").strip()
    invoice.save(update_fields=["status", "voided_at", "credit_minor", "notes", "updated_at"])
    return invoice


def mark_overdue(*, as_of: date | None = None) -> int:
    """Flip past-due PENDING invoices to OVERDUE. Returns how many moved.

    A sweep rather than a computed property because OVERDUE is the trigger for
    downstream behaviour (dunning, notifications), and things that trigger
    behaviour need an event, not a value that silently becomes true.
    """
    as_of = as_of or timezone.now().date()
    return Invoice.objects.filter(status=InvoiceStatus.PENDING, due_date__lt=as_of).update(
        status=InvoiceStatus.OVERDUE, updated_at=timezone.now()
    )


# --------------------------------------------------------------------- credits
@transaction.atomic
def issue_credit(
    *,
    tenant_id,
    amount_minor: int,
    currency: str,
    kind: str = CreditKind.GOODWILL,
    reason: str = "",
    issued_by=None,
    expires_at=None,
) -> Credit:
    if amount_minor <= 0:
        raise InvoicingError("A credit must be for a positive amount.")
    return Credit.objects.create(
        tenant_id=tenant_id,
        amount_minor=amount_minor,
        remaining_minor=amount_minor,
        currency=currency.upper(),
        kind=kind,
        reason=reason,
        issued_by=issued_by,
        expires_at=expires_at,
    )


@transaction.atomic
def void_credit(*, credit: Credit, reason: str = "") -> Credit:
    """Withdraw the unspent portion of a credit.

    Only the remainder is withdrawn — credit already applied to an issued
    invoice has been spent, and clawing it back would reopen a settled bill.
    """
    if credit.voided_at is not None:
        return credit
    credit.remaining_minor = 0
    credit.voided_at = timezone.now()
    if reason:
        credit.reason = (credit.reason + f"\nVoided: {reason}").strip()
    credit.save(update_fields=["remaining_minor", "voided_at", "reason", "updated_at"])
    return credit


def credit_balance(*, tenant_id, currency: str) -> int:
    """Live, unexpired credit for a tenant. Computed, never stored."""
    now = timezone.now()
    rows = (
        Credit.objects.filter(
            tenant_id=tenant_id,
            currency=currency.upper(),
            voided_at__isnull=True,
            remaining_minor__gt=0,
        )
        .exclude(expires_at__lt=now)
        .values_list("remaining_minor", flat=True)
    )
    return sum(rows)


# --------------------------------------------------------------------- from subs
@transaction.atomic
def invoice_for_subscription_period(
    *,
    subscription: Subscription,
    plan: Plan | None = None,
    issue_date: date | None = None,
    tax_rate_bps: int = 0,
    tax_label: str = "",
    billing_email: str = "",
    billing_name: str = "",
    billing_country: str = "",
    issue: bool = True,
) -> Invoice:
    """Produce the invoice for one subscription period.

    Idempotent per (subscription, period start): re-running a billing sweep, or
    replaying a webhook, must not bill a customer twice. The existing invoice
    is returned instead — the same replay-safety discipline the finance module
    applies to recurring transactions.
    """
    plan = plan or subscription.plan
    period_start = subscription.current_period_start or timezone.now()
    period_end = subscription.current_period_end

    existing = (
        Invoice.objects.filter(
            subscription=subscription,
            metadata__period_start=period_start.date().isoformat(),
        )
        .exclude(status=InvoiceStatus.CANCELLED)
        .first()
    )
    if existing is not None:
        return existing

    line = LineItemSpec(
        description=f"{plan.name} — {plan.get_interval_display()}",
        amount_minor=plan.price_minor,
        quantity=1,
        unit_amount_minor=plan.price_minor,
        period_start=period_start.date(),
        period_end=period_end.date() if period_end else None,
    )
    invoice = create_invoice(
        tenant_id=subscription.tenant_id,
        currency=plan.currency,
        line_items=[line],
        subscription=subscription,
        issue_date=issue_date,
        tax_rate_bps=tax_rate_bps,
        tax_label=tax_label,
        billing_email=billing_email,
        billing_name=billing_name,
        billing_country=billing_country,
        status=InvoiceStatus.DRAFT,
    )
    invoice.metadata = {**(invoice.metadata or {}), "period_start": period_start.date().isoformat()}
    invoice.save(update_fields=["metadata", "updated_at"])

    if issue:
        issue_invoice(invoice=invoice)
    return invoice


def reconcile_payment(*, payment: Payment, invoice: Invoice) -> Invoice:
    """Manually attach a payment to an invoice (bank transfer, cash, correction).

    The escape hatch for money that arrived outside the provider rails. Kept in
    the service layer, and audited by its platform caller, precisely because
    manual reconciliation is the operation most worth being able to review.
    """
    if payment.status != PaymentStatus.SUCCEEDED:
        raise InvoicingError("Only a succeeded payment can be reconciled against an invoice.")
    if payment.currency.upper() != invoice.currency.upper():
        raise InvoicingError(
            f"Currency mismatch: payment is {payment.currency}, invoice is {invoice.currency}."
        )
    return mark_paid(invoice=invoice, amount_minor=payment.amount_minor, payment=payment)
