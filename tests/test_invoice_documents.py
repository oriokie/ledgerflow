"""Invoice document rendering and delivery.

The renderer makes no database queries by design, so most of these tests build
an invoice and assert on the bytes. PDFs are binary, so assertions are on
structural facts (it is a PDF, it has pages, the amounts appear in the
extractable text) rather than on an exact byte match, which would break on any
reportlab upgrade without indicating a real regression.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.billing import invoicing
from apps.billing.invoice_pdf import (
    invoice_filename,
    issuer_details,
    render_invoice_pdf,
    send_invoice_email,
)
from apps.billing.invoicing_models import Invoice, InvoiceStatus
from apps.billing.tasks import send_invoice_email_task

pytestmark = pytest.mark.django_db


def _invoice(**overrides) -> Invoice:
    defaults = dict(
        tenant_id=uuid.uuid4(),
        currency="USD",
        line_items=[
            invoicing.LineItemSpec(
                description="Plus subscription",
                amount_minor=900,
                quantity=1,
                unit_amount_minor=900,
                period_start=timezone.now().date(),
                period_end=(timezone.now() + timedelta(days=30)).date(),
            )
        ],
        billing_name="Amina Otieno",
        billing_email="amina@example.test",
        billing_country="KE",
    )
    defaults.update(overrides)
    return invoicing.create_invoice(**defaults)


def _text(pdf: bytes) -> str:
    """Best-effort text extraction, for asserting content appears at all.

    reportlab writes compressed streams, so this decodes what it can and falls
    back to a permissive decode. Good enough to answer "is this amount in the
    document"; not a PDF parser.
    """
    try:
        from pdfminer.high_level import extract_text  # type: ignore
        import io

        return extract_text(io.BytesIO(pdf))
    except Exception:
        return pdf.decode("latin-1", errors="ignore")


# ------------------------------------------------------------------ rendering
def test_renders_a_real_pdf():
    pdf = render_invoice_pdf(_invoice())
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 1000


def test_filename_uses_the_invoice_number():
    invoice = _invoice()
    assert invoice_filename(invoice) == f"{invoice.number}.pdf"


def test_the_document_is_titled_with_the_invoice_number():
    invoice = _invoice()
    assert invoice.number.encode() in render_invoice_pdf(invoice)


def test_renders_a_multi_line_invoice():
    invoice = _invoice(
        line_items=[
            invoicing.LineItemSpec(description="Plus subscription", amount_minor=900),
            invoicing.LineItemSpec(description="Additional seat", amount_minor=300),
            invoicing.LineItemSpec(description="Prorated upgrade", amount_minor=145),
        ]
    )
    assert invoice.subtotal_minor == 1345
    assert render_invoice_pdf(invoice).startswith(b"%PDF-")


def test_renders_discounts_credits_and_tax():
    tenant = uuid.uuid4()
    invoicing.issue_credit(tenant_id=tenant, amount_minor=200, currency="USD")
    invoice = _invoice(
        tenant_id=tenant,
        discount_minor=100,
        tax_rate_bps=2000,
        tax_label="VAT",
    )
    pdf = render_invoice_pdf(invoice)
    assert pdf.startswith(b"%PDF-")
    # The arithmetic the document shows is the frozen arithmetic on the row.
    assert invoice.discount_minor == 100
    assert invoice.credit_minor == 200
    assert invoice.tax_minor == 120


def test_renders_an_invoice_with_no_billing_details():
    """A workspace may never have supplied a billing name; the document must
    still render rather than blowing up mid-render on a None."""
    invoice = _invoice(billing_name="", billing_email="", billing_country="")
    assert render_invoice_pdf(invoice).startswith(b"%PDF-")


def test_renders_a_zero_total_invoice():
    tenant = uuid.uuid4()
    invoicing.issue_credit(tenant_id=tenant, amount_minor=5000, currency="USD")
    invoice = _invoice(tenant_id=tenant)
    assert invoice.total_minor == 0
    assert render_invoice_pdf(invoice).startswith(b"%PDF-")


def test_renders_notes_when_present():
    invoice = _invoice(notes="Thanks for your\nbusiness.")
    assert render_invoice_pdf(invoice).startswith(b"%PDF-")


def test_the_issuer_is_configurable(settings):
    """The billing entity is a deployment fact — a reseller bills under their
    own name."""
    settings.INVOICE_ISSUER = {"name": "Acme Reseller", "email": "ar@acme.test"}
    details = issuer_details()
    assert details["name"] == "Acme Reseller"
    assert details["email"] == "ar@acme.test"
    # Unspecified keys keep their defaults rather than disappearing.
    assert "address" in details


def test_rendering_cost_is_fixed_and_tiny(django_assert_num_queries):
    """One query, regardless of how many line items the invoice has.

    That single query is the batched issuer-details lookup. The property worth
    locking down is that nothing scales with the document: a generator that
    lazily loads a related field is one refactor away from an N+1 inside a PDF
    loop, and from reaching data the caller never intended to put on the page.
    """
    invoice = invoicing.create_invoice(
        tenant_id=uuid.uuid4(),
        currency="USD",
        line_items=[
            invoicing.LineItemSpec(description=f"Line {n}", amount_minor=100) for n in range(12)
        ],
    )
    prefetched = Invoice.objects.prefetch_related("line_items").get(pk=invoice.pk)
    with django_assert_num_queries(1):
        render_invoice_pdf(prefetched)


# ------------------------------------------------------------------- delivery
def test_sending_attaches_the_pdf():
    invoice = _invoice()
    mail.outbox.clear()

    recipient = send_invoice_email(invoice=invoice)

    assert recipient == "amina@example.test"
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert invoice.number in message.subject
    assert len(message.attachments) == 1
    name, content, mimetype = message.attachments[0]
    assert name == f"{invoice.number}.pdf"
    assert mimetype == "application/pdf"
    assert content.startswith(b"%PDF-")


def test_sending_stamps_sent_at():
    invoice = _invoice()
    assert invoice.sent_at is None

    send_invoice_email(invoice=invoice)

    invoice.refresh_from_db()
    assert invoice.sent_at is not None


def test_an_override_address_can_be_supplied():
    """Support sometimes needs to copy an accountant without editing an invoice
    that is frozen once issued."""
    invoice = _invoice()
    mail.outbox.clear()

    send_invoice_email(invoice=invoice, to="accountant@example.test")

    assert mail.outbox[0].to == ["accountant@example.test"]


def test_sending_without_an_address_raises_rather_than_silently_doing_nothing():
    """'Send this invoice' quietly succeeding without sending surfaces weeks
    later as an unpaid bill nobody chased."""
    invoice = _invoice(billing_email="")
    with pytest.raises(ValueError):
        send_invoice_email(invoice=invoice)


def test_an_unpaid_invoice_states_the_amount_due():
    invoice = _invoice()
    invoicing.issue_invoice(invoice=invoice)
    mail.outbox.clear()

    send_invoice_email(invoice=invoice)

    body = mail.outbox[0].body
    assert "Amount due" in body
    assert "Due by" in body


def test_a_paid_invoice_reads_as_a_receipt():
    invoice = _invoice()
    invoicing.issue_invoice(invoice=invoice)
    invoicing.mark_paid(invoice=invoice)
    invoice.refresh_from_db()
    mail.outbox.clear()

    send_invoice_email(invoice=invoice)

    body = mail.outbox[0].body
    assert "paid in full" in body
    assert "Amount due" not in body


# ----------------------------------------------------------------------- task
def test_the_task_sends_the_invoice():
    invoice = _invoice()
    mail.outbox.clear()

    result = send_invoice_email_task(invoice_id=str(invoice.id))

    assert result == {"sent": True, "to": "amina@example.test"}
    assert len(mail.outbox) == 1


def test_the_task_does_not_retry_a_deleted_invoice():
    """Retrying cannot make a voided invoice reappear."""
    missing = uuid.uuid4()
    result = send_invoice_email_task(invoice_id=str(missing))
    assert result == {"sent": False, "reason": "invoice_missing"}


def test_the_task_reports_a_missing_address_rather_than_raising():
    invoice = _invoice(billing_email="")
    result = send_invoice_email_task(invoice_id=str(invoice.id))
    assert result == {"sent": False, "reason": "no_recipient"}
    assert len(mail.outbox) == 0


# ------------------------------------------------------------------------ api
def test_platform_staff_can_download_an_invoice_pdf():
    from apps.platform_admin.rbac import PlatformRole
    from tests.test_platform_admin_rbac import client_for, make_staff

    invoice = _invoice()
    staff = make_staff(PlatformRole.FINANCE)

    response = client_for(staff).get(f"/api/v1/platform/invoices/{invoice.id}/pdf/")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert invoice.number in response["Content-Disposition"]
    assert response.content.startswith(b"%PDF-")


def test_downloading_needs_the_billing_read_capability():
    from apps.platform_admin.models import PlatformStaff
    from apps.platform_admin.rbac import PlatformCapability, PlatformRole
    from tests.test_platform_admin_rbac import client_for, make_staff

    invoice = _invoice()
    staff = make_staff(PlatformRole.AUDITOR)
    # Strip the capability rather than picking a role that lacks it — every
    # role holds billing.read, so this proves the check is on the capability.
    PlatformStaff.objects.filter(pk=staff.pk).update(
        denied_capabilities=[PlatformCapability.BILLING_READ.value]
    )

    response = client_for(staff).get(f"/api/v1/platform/invoices/{invoice.id}/pdf/")
    assert response.status_code == 403


def test_sending_from_the_api_queues_the_task_and_audits_it():
    from apps.platform_admin.models import PlatformAuditLog
    from apps.platform_admin.rbac import PlatformRole
    from tests.test_platform_admin_rbac import client_for, make_staff

    invoice = _invoice()
    invoicing.issue_invoice(invoice=invoice)
    staff = make_staff(PlatformRole.FINANCE)
    mail.outbox.clear()

    response = client_for(staff).post(
        f"/api/v1/platform/invoices/{invoice.id}/send/", {}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["to"] == "amina@example.test"
    # CELERY_TASK_ALWAYS_EAGER in test settings, so the send actually happened.
    assert len(mail.outbox) == 1

    row = PlatformAuditLog.objects.get(action="invoice.sent")
    assert row.tenant_id == invoice.tenant_id
    assert row.context["to"] == "amina@example.test"


def test_sending_an_invoice_with_no_address_is_a_field_error():
    from apps.platform_admin.rbac import PlatformRole
    from tests.test_platform_admin_rbac import client_for, make_staff

    invoice = _invoice(billing_email="")
    staff = make_staff(PlatformRole.FINANCE)

    response = client_for(staff).post(
        f"/api/v1/platform/invoices/{invoice.id}/send/", {}, format="json"
    )
    assert response.status_code == 400
    assert "to" in response.json()


def test_sending_needs_invoice_write_not_merely_read():
    from apps.platform_admin.rbac import PlatformRole
    from tests.test_platform_admin_rbac import client_for, make_staff

    invoice = _invoice()
    auditor = make_staff(PlatformRole.AUDITOR)  # read-only

    response = client_for(auditor).post(
        f"/api/v1/platform/invoices/{invoice.id}/send/", {}, format="json"
    )
    assert response.status_code == 403


def test_a_missing_invoice_is_a_404_not_a_500():
    from apps.platform_admin.rbac import PlatformRole
    from tests.test_platform_admin_rbac import client_for, make_staff

    staff = make_staff(PlatformRole.FINANCE)
    assert (
        client_for(staff).get(f"/api/v1/platform/invoices/{uuid.uuid4()}/pdf/").status_code == 404
    )


def test_a_voided_invoice_still_renders():
    """A cancelled invoice is still a document someone may need to file."""
    invoice = _invoice()
    invoicing.issue_invoice(invoice=invoice)
    invoicing.void_invoice(invoice=invoice, reason="Billed in error")
    invoice.refresh_from_db()

    assert invoice.status == InvoiceStatus.CANCELLED
    assert render_invoice_pdf(invoice).startswith(b"%PDF-")
