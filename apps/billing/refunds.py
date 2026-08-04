"""Refund workflow.

A refund is a two-person operation by design: `request_refund` records an
intention, `approve_refund` moves money. The platform RBAC hands those two
capabilities to different roles (Customer Success can request; Finance
approves), and this module is where that split becomes real rather than
advisory — there is no single call that does both.

The over-refund guard is the other thing this module exists for. Refunds
accumulate against one payment, and "how much is left to refund" must account
for refunds that are still in flight, not only ones that have settled.
Otherwise two support agents each refunding "the remaining half" of a payment
within the same minute both pass validation and the platform pays out 150%.
"""

from __future__ import annotations

import logging
import uuid

from django.db import transaction
from django.utils import timezone

from .invoicing_models import Invoice, InvoiceStatus, Refund, RefundStatus
from .models import Payment, PaymentStatus
from .providers import get_provider
from .providers.base import PaymentError

logger = logging.getLogger("ledgerflow.billing.refunds")

#: Statuses that represent money either already returned or committed to being
#: returned. Both count against the refundable balance.
COMMITTED_STATUSES = (
    RefundStatus.REQUESTED,
    RefundStatus.APPROVED,
    RefundStatus.PROCESSING,
    RefundStatus.SUCCEEDED,
)


class RefundError(Exception):
    """Raised when a refund is not valid in the current state."""


def refunded_minor(*, payment: Payment) -> int:
    """Sum of settled and in-flight refunds against a payment."""
    rows = Refund.objects.filter(payment=payment, status__in=COMMITTED_STATUSES).values_list(
        "amount_minor", flat=True
    )
    return sum(rows)


def refundable_minor(*, payment: Payment) -> int:
    return max(payment.amount_minor - refunded_minor(payment=payment), 0)


@transaction.atomic
def request_refund(
    *,
    payment: Payment,
    amount_minor: int | None = None,
    reason: str,
    requested_by=None,
    invoice: Invoice | None = None,
) -> Refund:
    """Record a refund request. Moves no money.

    `amount_minor=None` means "refund whatever is left", which is what a full
    refund means once a partial one has already happened.
    """
    if not reason or not reason.strip():
        raise RefundError("A refund needs a reason.")
    if payment.status != PaymentStatus.SUCCEEDED:
        raise RefundError("Only a succeeded payment can be refunded.")

    # Lock the payment row so concurrent requests serialise on the same
    # refundable-balance read.
    payment = Payment.objects.select_for_update().get(pk=payment.pk)

    available = refundable_minor(payment=payment)
    if available <= 0:
        raise RefundError("This payment has already been fully refunded.")

    amount = available if amount_minor is None else int(amount_minor)
    if amount <= 0:
        raise RefundError("A refund must be for a positive amount.")
    if amount > available:
        raise RefundError(f"Refund of {amount} exceeds the {available} still refundable on this payment.")

    return Refund.objects.create(
        tenant_id=payment.tenant_id,
        payment=payment,
        invoice=invoice,
        amount_minor=amount,
        currency=payment.currency,
        reason=reason.strip(),
        requested_by=requested_by,
        provider=payment.provider,
        status=RefundStatus.REQUESTED,
    )


@transaction.atomic
def reject_refund(*, refund: Refund, approved_by=None, note: str = "") -> Refund:
    if refund.status != RefundStatus.REQUESTED:
        raise RefundError(f"Only a requested refund can be rejected (this one is {refund.status}).")
    refund.status = RefundStatus.REJECTED
    refund.approved_by = approved_by
    refund.approved_at = timezone.now()
    refund.decision_note = note
    refund.save(update_fields=["status", "approved_by", "approved_at", "decision_note", "updated_at"])
    return refund


@transaction.atomic
def approve_refund(*, refund: Refund, approved_by=None, note: str = "") -> Refund:
    """Approve and execute. This is the call that moves money.

    Approval and execution are one step on purpose. An APPROVED-but-not-sent
    refund is a promise the system has made and not kept, and every extra state
    a refund can be stranded in is another state someone has to sweep. The
    asynchronous case is still represented — providers that settle later return
    PROCESSING, which a webhook resolves.
    """
    if refund.status != RefundStatus.REQUESTED:
        raise RefundError(f"Only a requested refund can be approved (this one is {refund.status}).")
    if refund.requested_by_id and approved_by is not None and refund.requested_by_id == approved_by.id:
        # The RBAC split is pointless if one person holding both capabilities
        # can satisfy it alone.
        raise RefundError("A refund must be approved by someone other than the person who requested it.")

    refund.status = RefundStatus.APPROVED
    refund.approved_by = approved_by
    refund.approved_at = timezone.now()
    refund.decision_note = note
    refund.save(update_fields=["status", "approved_by", "approved_at", "decision_note", "updated_at"])

    return _execute(refund=refund)


def _execute(*, refund: Refund) -> Refund:
    payment = refund.payment
    try:
        provider = get_provider(refund.provider or payment.provider)
    except ValueError as exc:
        return _fail(refund, str(exc))

    if not getattr(provider, "supports_refunds", False):
        return _fail(refund, f"The {provider.key} provider cannot process refunds.")

    try:
        result = provider.refund(
            charge_ref=payment.provider_ref,
            amount_minor=refund.amount_minor,
            currency=refund.currency,
            reason=refund.reason,
            idempotency_key=f"refund-{refund.id}",
        )
    except PaymentError as exc:
        return _fail(refund, str(exc))

    refund.provider_ref = result.provider_ref
    if result.status == "succeeded":
        refund.status = RefundStatus.SUCCEEDED
        refund.completed_at = timezone.now()
    elif result.status == "pending":
        refund.status = RefundStatus.PROCESSING
    else:
        return _fail(refund, result.failure_reason or "The provider declined the refund.")
    refund.save(update_fields=["provider_ref", "status", "completed_at", "updated_at"])

    if refund.status == RefundStatus.SUCCEEDED:
        _settle(refund)
    return refund


def _fail(refund: Refund, message: str) -> Refund:
    refund.status = RefundStatus.FAILED
    refund.failure_reason = message[:255]
    refund.save(update_fields=["status", "failure_reason", "updated_at"])
    logger.warning("refund %s failed: %s", refund.id, message)
    return refund


def _settle(refund: Refund) -> None:
    """Reflect a settled refund on the payment and any linked invoice.

    The payment is only marked REFUNDED once *everything* has been returned; a
    partial refund leaves it SUCCEEDED, because it is still, in part, a
    successful collection.
    """
    payment = refund.payment
    if refunded_minor(payment=payment) >= payment.amount_minor:
        payment.status = PaymentStatus.REFUNDED
        payment.save(update_fields=["status", "updated_at"])

        invoice = refund.invoice
        if invoice is not None and invoice.status == InvoiceStatus.PAID:
            invoice.status = InvoiceStatus.REFUNDED
            invoice.save(update_fields=["status", "updated_at"])


@transaction.atomic
def settle_pending_refund(*, provider_ref: str, succeeded: bool, failure_reason: str = "") -> Refund | None:
    """Resolve a PROCESSING refund from a provider webhook.

    Returns None for an unknown reference rather than raising: providers send
    events for objects we did not create (a refund issued from their dashboard),
    and a webhook endpoint that 500s on those will be throttled or disabled by
    the provider.
    """
    refund = Refund.objects.select_for_update().filter(provider_ref=provider_ref).first()
    if refund is None or refund.status != RefundStatus.PROCESSING:
        return refund

    if succeeded:
        refund.status = RefundStatus.SUCCEEDED
        refund.completed_at = timezone.now()
        refund.save(update_fields=["status", "completed_at", "updated_at"])
        _settle(refund)
    else:
        _fail(refund, failure_reason or "The provider could not complete the refund.")
    return refund


def new_idempotency_key() -> str:
    return uuid.uuid4().hex
