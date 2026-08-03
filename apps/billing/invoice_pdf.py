"""Invoice rendering and delivery.

The PDF is generated on demand, never stored. An invoice's arithmetic is
already frozen on the row (see `invoicing.py`), so the document is fully
reproducible from it — and *not* storing it means there is exactly one source
of truth. A cached PDF that disagrees with the invoice it claims to represent
is worse than no PDF, and object storage of a document we can rebuild in
milliseconds is cost without benefit.

Delivery is asynchronous, following the same reasoning as invitation email: a
slow mail provider must never block the request that issued the invoice.

The renderer deliberately makes no database queries. It takes the invoice and
its line items and formats them — so it is testable without a mail server, an
API request, or a tenant context, and cannot accidentally leak a field that
was not already on the document.
"""

from __future__ import annotations

import io
import logging
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .invoicing_models import Invoice, InvoiceStatus

logger = logging.getLogger("ledgerflow.billing.invoice_pdf")

#: Shown in the document header. Configurable because the entity issuing the
#: invoice is a deployment fact, not a product one — a reseller running their
#: own LedgerFlow bills under their own name.
DEFAULT_ISSUER = {
    "name": "LedgerFlow",
    "address": "",
    "email": "billing@ledgerflow.app",
    "tax_id": "",
}


def issuer_details() -> dict[str, str]:
    """Resolve the issuing entity: admin-set values, then settings, then default.

    The platform console can edit these, so a finance team can correct a tax ID
    without a deploy — and getting a tax ID wrong on issued invoices is exactly
    the sort of thing discovered at quarter end.
    """
    resolved = {**DEFAULT_ISSUER, **getattr(settings, "INVOICE_ISSUER", {})}

    fields = {
        "invoice.issuer_name": "name",
        "invoice.issuer_address": "address",
        "invoice.issuer_email": "email",
        "invoice.issuer_tax_id": "tax_id",
    }
    try:
        from apps.platform_admin.settings_store import get_overrides

        # Only values an operator actually set in the console. Using the
        # store's `get()` here would let its *built-in default* displace an
        # explicitly configured `INVOICE_ISSUER`, which is precedence exactly
        # backwards: a deployment that states its own issuer means it.
        for key, value in get_overrides(list(fields)).items():
            resolved[fields[key]] = value
    except Exception:  # noqa: BLE001
        # Rendering must not fail because the settings table is unavailable or
        # unmigrated; the defaults are always serviceable.
        logger.warning("platform settings unavailable; using default issuer details")
    return resolved


def _amount(minor: int, currency: str) -> str:
    """Minor units → a document-ready string.

    Two decimal places rather than locale-aware currency formatting: an invoice
    is read by accountants and tax authorities in an unknown locale, and
    `1.234,56` vs `1,234.56` ambiguity on a legal document is not worth the
    prettier output. The currency code is always adjacent.
    """
    return f"{Decimal(minor) / 100:,.2f} {currency}"


def render_invoice_pdf(invoice: Invoice) -> bytes:
    """Render one invoice as a PDF document.

    Reads `invoice.line_items` — pass an invoice fetched with
    `prefetch_related("line_items")` to avoid a second query.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    issuer = issuer_details()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=f"Invoice {invoice.number}",
        author=issuer["name"],
        subject=f"Invoice {invoice.number}",
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    styles = getSampleStyleSheet()
    muted = ParagraphStyle(
        "muted", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#656c81")
    )
    story: list = []

    # ---------------------------------------------------------------- header
    story.append(Paragraph(f"Invoice {invoice.number}", styles["Title"]))
    story.append(Spacer(1, 2 * mm))

    status_note = {
        InvoiceStatus.PAID: "Paid — no action required.",
        InvoiceStatus.CANCELLED: "Cancelled — this invoice is void.",
        InvoiceStatus.REFUNDED: "Refunded.",
        InvoiceStatus.OVERDUE: "Overdue — payment is past its due date.",
        InvoiceStatus.DRAFT: "Draft — not yet issued.",
    }.get(invoice.status, "")
    if status_note:
        story.append(Paragraph(status_note, muted))
        story.append(Spacer(1, 3 * mm))

    # Issuer and recipient side by side. The billing snapshot on the invoice is
    # used rather than the tenant's current details — the document must keep
    # showing what was true when it was issued.
    from_block = "<br/>".join(
        part
        for part in [
            f"<b>{issuer['name']}</b>",
            issuer["address"],
            issuer["email"],
            f"Tax ID: {issuer['tax_id']}" if issuer["tax_id"] else "",
        ]
        if part
    )
    to_block = "<br/>".join(
        part
        for part in [
            "<b>Billed to</b>",
            invoice.billing_name or "—",
            invoice.billing_email,
            invoice.billing_country,
        ]
        if part
    )
    parties = Table(
        [[Paragraph(from_block, muted), Paragraph(to_block, muted)]],
        colWidths=[87 * mm, 87 * mm],
    )
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(parties)
    story.append(Spacer(1, 6 * mm))

    meta_rows = [
        ["Issue date", invoice.issue_date.strftime("%d %B %Y")],
        ["Due date", invoice.due_date.strftime("%d %B %Y")],
        ["Status", invoice.get_status_display()],
        ["Currency", invoice.currency],
    ]
    if invoice.paid_at:
        meta_rows.append(["Paid on", invoice.paid_at.strftime("%d %B %Y")])
    meta = Table(meta_rows, colWidths=[35 * mm, 60 * mm])
    meta.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#656c81")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(meta)
    story.append(Spacer(1, 7 * mm))

    # ------------------------------------------------------------- line items
    line_header = ["Description", "Period", "Qty", "Unit", "Amount"]
    lines = [line_header]
    for item in invoice.line_items.all():
        period = ""
        if item.period_start:
            period = item.period_start.strftime("%d %b %Y")
            if item.period_end:
                period += f" – {item.period_end.strftime('%d %b %Y')}"
        lines.append(
            [
                Paragraph(item.description, styles["BodyText"]),
                period,
                str(item.quantity),
                _amount(item.unit_amount_minor, invoice.currency),
                _amount(item.amount_minor, invoice.currency),
            ]
        )

    table = Table(lines, colWidths=[62 * mm, 38 * mm, 12 * mm, 30 * mm, 32 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f1f5")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e3e6ec")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 5 * mm))

    # ---------------------------------------------------------------- totals
    # Mirrors the arithmetic order frozen on the row: subtotal, discount,
    # credit, then tax on what remains.
    totals: list[list] = [["Subtotal", _amount(invoice.subtotal_minor, invoice.currency)]]
    if invoice.discount_minor:
        totals.append(["Discount", f"-{_amount(invoice.discount_minor, invoice.currency)}"])
    if invoice.credit_minor:
        totals.append(["Account credit", f"-{_amount(invoice.credit_minor, invoice.currency)}"])
    if invoice.tax_minor or invoice.tax_rate_bps:
        label = invoice.tax_label or "Tax"
        if invoice.tax_rate_bps:
            label += f" ({invoice.tax_rate_bps / 100:g}%)"
        totals.append([label, _amount(invoice.tax_minor, invoice.currency)])
    totals.append(["Total", _amount(invoice.total_minor, invoice.currency)])
    if invoice.amount_paid_minor:
        totals.append(["Paid", f"-{_amount(invoice.amount_paid_minor, invoice.currency)}"])
        totals.append(["Amount due", _amount(invoice.amount_due_minor, invoice.currency)])

    totals_table = Table(totals, colWidths=[42 * mm, 42 * mm], hAlign="RIGHT")
    totals_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("TEXTCOLOR", (0, 0), (0, -2), colors.HexColor("#656c81")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.HexColor("#9aa1b4")),
                ("TOPPADDING", (0, -1), (-1, -1), 5),
            ]
        )
    )
    story.append(totals_table)

    if invoice.notes:
        story.append(Spacer(1, 7 * mm))
        story.append(Paragraph("<b>Notes</b>", muted))
        story.append(Paragraph(invoice.notes.replace("\n", "<br/>"), muted))

    story.append(Spacer(1, 10 * mm))
    story.append(
        Paragraph(
            f"Generated {timezone.now():%d %B %Y}. "
            f"Questions? Reply to {issuer['email']}.",
            muted,
        )
    )

    doc.build(story)
    return buffer.getvalue()


def invoice_filename(invoice: Invoice) -> str:
    return f"{invoice.number}.pdf"


# ------------------------------------------------------------------ delivery
def _email_body(invoice: Invoice) -> str:
    issuer = issuer_details()
    if invoice.status == InvoiceStatus.PAID:
        opening = f"Thanks — invoice {invoice.number} is paid in full. A copy is attached."
        action = ""
    else:
        opening = f"Invoice {invoice.number} is attached."
        action = (
            f"\n\nAmount due: {_amount(invoice.amount_due_minor, invoice.currency)}"
            f"\nDue by: {invoice.due_date:%d %B %Y}"
        )
    return (
        f"Hello,\n\n{opening}{action}\n\n"
        f"Issued: {invoice.issue_date:%d %B %Y}\n"
        f"Total: {_amount(invoice.total_minor, invoice.currency)}\n\n"
        f"If anything looks wrong, reply to this message and a person will look at it.\n\n"
        f"— {issuer['name']}\n"
    )


def send_invoice_email(*, invoice: Invoice, to: str = "") -> str:
    """Email the invoice with its PDF attached. Returns the address used.

    Raises `ValueError` when there is no address rather than silently doing
    nothing: "send this invoice" quietly succeeding without sending is the kind
    of failure that surfaces weeks later as an unpaid bill nobody chased.
    """
    from django.core.mail import EmailMessage

    recipient = (to or invoice.billing_email or "").strip()
    if not recipient:
        raise ValueError("This invoice has no billing email address to send to.")

    issuer = issuer_details()
    message = EmailMessage(
        subject=f"{issuer['name']} invoice {invoice.number}",
        body=_email_body(invoice),
        to=[recipient],
    )
    message.attach(invoice_filename(invoice), render_invoice_pdf(invoice), "application/pdf")
    message.send(fail_silently=False)

    Invoice.objects.filter(pk=invoice.pk).update(sent_at=timezone.now())
    logger.info("invoice %s emailed to %s", invoice.number, recipient)
    return recipient
