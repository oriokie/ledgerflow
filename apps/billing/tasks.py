"""Asynchronous billing work.

Invoice delivery is a task rather than an inline call for the same reason
invitation email is: a slow or unreachable mail provider must never block the
API request that issued the invoice. The invoice exists and is correct whether
or not the email lands, and a failed send is a retryable delivery problem, not
a billing failure.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("ledgerflow.billing.tasks")


@shared_task(bind=True, max_retries=3, default_retry_delay=60, name="billing.send_invoice_email")
def send_invoice_email_task(self, *, invoice_id: str, to: str = "") -> dict:
    """Render and email one invoice.

    A missing invoice is not retried — it was voided or deleted between the
    request and the task, and retrying cannot make it reappear. A missing
    address is likewise permanent. Both return a reason rather than raising, so
    the failure shows up in the task result instead of as a stack trace.
    Everything else (SMTP timeouts, transient provider errors) is retried with
    backoff.
    """
    from .invoice_pdf import send_invoice_email
    from .invoicing_models import Invoice

    invoice = Invoice.objects.prefetch_related("line_items").filter(id=invoice_id).first()
    if invoice is None:
        logger.warning("invoice %s no longer exists; not sending", invoice_id)
        return {"sent": False, "reason": "invoice_missing"}

    try:
        recipient = send_invoice_email(invoice=invoice, to=to)
    except ValueError as exc:
        logger.warning("invoice %s not sent: %s", invoice_id, exc)
        return {"sent": False, "reason": "no_recipient"}
    except Exception as exc:  # noqa: BLE001 — transient delivery failure
        logger.warning("invoice %s send failed, retrying: %s", invoice_id, exc)
        raise self.retry(exc=exc) from exc

    return {"sent": True, "to": recipient}
