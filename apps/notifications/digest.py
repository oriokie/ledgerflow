"""The weekly money digest — the Monday note.

The monthly summary answers "was last month fine?". This answers the smaller,
more frequent question that actually steers behaviour: *what does this week
look like?* Safe to spend today, what last week did, what's due before next
Monday, and the coach's top findings — four things, in the preview pane,
because a digest that tries to be the dashboard gets skimmed once and then
filtered forever.

Everything is read from selectors the product already trusts: the safe-to-
spend figure is the cash-flow trough (the same one on the dashboard), the
bills come from the bills table, the findings from the live insight feed.
Nothing here computes anything new, which is why it stays correct as those
improve.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from apps.common.frontend_urls import build
from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant

logger = logging.getLogger("ledgerflow.notifications.digest")


def _money(minor: int | None, currency: str) -> str:
    if minor is None:
        return "—"
    return f"{currency} {minor / 100:,.2f}"


def build_digest(*, base_currency: str, as_of: date | None = None) -> dict:
    """Assemble the week's figures. Caller must hold the tenant context."""
    from apps.finance import cashflow_calendar as cc
    from apps.finance.models import Bill, BillStatus, Transaction
    from apps.intelligence import coach

    as_of = as_of or timezone.localdate()
    week_ago = as_of - timedelta(days=7)
    week_ahead = as_of + timedelta(days=7)

    rows = Transaction.objects.filter(
        occurred_at__date__gte=week_ago,
        occurred_at__date__lt=as_of,
        currency=base_currency,
    ).values_list("amount_minor", flat=True)
    inflow = sum(v for v in rows if v > 0)
    outflow = -sum(v for v in rows if v < 0)

    calendar = cc.cashflow_calendar(days=35, currency=base_currency)

    bills = [
        {"name": bill.name, "amount_minor": bill.amount_minor, "due_on": bill.due_on}
        for bill in Bill.objects.filter(
            status=BillStatus.UPCOMING,
            currency=base_currency,
            due_on__gte=as_of,
            due_on__lte=week_ahead,
        ).order_by("due_on")
    ]

    findings = [
        {"title": insight.title, "severity": insight.severity} for insight in coach.live_insights(limit=3)
    ]

    return {
        "as_of": as_of,
        "inflow_minor": inflow,
        "outflow_minor": outflow,
        "safe_to_spend_minor": calendar.safe_to_spend_minor if calendar else None,
        "first_negative_on": calendar.first_negative_on if calendar else None,
        "bills": bills,
        "findings": findings,
    }


def render_digest_text(digest: dict, *, currency: str, name: str = "") -> str:
    greeting = f"Hi {name}," if name else "Hi,"
    lines = [greeting, ""]

    # Safe-to-spend leads: it is the one figure that changes what someone does
    # *today*, which is the entire argument for a weekly cadence.
    if digest["safe_to_spend_minor"] is not None:
        lines.append(f"Safe to spend: {_money(digest['safe_to_spend_minor'], currency)}")
        if digest["first_negative_on"]:
            lines.append(
                f"  (heads up: projected to dip below zero around " f"{digest['first_negative_on']:%-d %b})"
            )
        lines.append("")

    lines += [
        "Last week",
        f"  Money in    {_money(digest['inflow_minor'], currency)}",
        f"  Money out   {_money(digest['outflow_minor'], currency)}",
        "",
    ]

    if digest["bills"]:
        lines.append("Due this week")
        for bill in digest["bills"]:
            lines.append(
                f"  {bill['due_on']:%a %-d %b}  {bill['name']}  {_money(bill['amount_minor'], currency)}"
            )
        lines.append("")

    if digest["findings"]:
        lines.append("Worth a look")
        for finding in digest["findings"]:
            lines.append(f"  • {finding['title']}")
        lines.append("")

    lines += [
        f"Open LedgerFlow: {build('')}",
        "",
        f"Don't want the weekly note? Turn it off here: {build('settings/preferences')}",
    ]
    return "\n".join(lines)


def render_digest_html(digest: dict, *, currency: str, name: str = "") -> str:
    """The HTML twin of the text body — same information, same order.

    The preheader is the safe-to-spend figure itself: it is the reason to open
    the email, and in most clients it is read from the inbox list more often
    than the body is read at all.
    """
    from . import email_html as h

    safe = digest["safe_to_spend_minor"]
    preheader = f"Safe to spend: {_money(safe, currency)}" if safe is not None else "Your week ahead"

    parts: list[str] = []
    if safe is not None:
        parts.append(
            h.hero(
                _money(safe, currency),
                "safe to spend — every bill in the projection still covered",
                tone="danger" if safe == 0 else "accent",
            )
        )
        if digest["first_negative_on"]:
            parts.append(
                h.note(
                    f"Heads up: projected to dip below zero around " f"{digest['first_negative_on']:%-d %b}."
                )
            )

    parts.append(h.section("Last week"))
    parts.append(
        h.figure_row(
            [
                ("Money in", _money(digest["inflow_minor"], currency)),
                ("Money out", _money(digest["outflow_minor"], currency)),
            ]
        )
    )

    if digest["bills"]:
        parts.append(h.section("Due this week"))
        parts.append(
            h.figure_row(
                [
                    (
                        f"{bill['due_on']:%a %-d %b} — {bill['name']}",
                        _money(bill["amount_minor"], currency),
                    )
                    for bill in digest["bills"]
                ]
            )
        )

    if digest["findings"]:
        parts.append(h.section("Worth a look"))
        parts.append(h.bullet_list([finding["title"] for finding in digest["findings"]]))

    parts.append(h.button("Open LedgerFlow", build("")))

    greeting_name = name or "there"
    return h.wrap(
        preheader=preheader,
        title=f"Hi {greeting_name} — your week ahead",
        body_html="".join(parts),
        footer_links=[
            ("Preferences", build("settings/preferences")),
            ("Open the app", build("")),
        ],
    )


def send_weekly_digest_for_tenant(*, tenant_id, as_of: date | None = None) -> int:
    """Email every opted-in member of one workspace. Returns how many sent."""
    from apps.tenancy.models import Membership, Tenant

    from .models import NotificationPreference

    tenant = Tenant.objects.filter(id=tenant_id).first()
    if tenant is None:
        return 0

    with transaction.atomic():
        bind_db_tenant(tenant_id)
        with use_tenant(tenant_id):
            digest = build_digest(base_currency=tenant.base_currency, as_of=as_of)
            # A workspace with nothing moving, nothing due and nothing found
            # gets no email. "All quiet" every Monday is how the one Monday
            # that matters gets filtered with the rest.
            if (
                not digest["inflow_minor"]
                and not digest["outflow_minor"]
                and not digest["bills"]
                and not digest["findings"]
            ):
                return 0
            opted_in = {
                p.user_id
                for p in NotificationPreference.objects.filter(weekly_digest=True, email_enabled=True)
            }

    sent = 0
    for membership in Membership.objects.filter(tenant_id=tenant_id).select_related("user"):
        if membership.user_id not in opted_in or not membership.user.email:
            continue
        text = render_digest_text(
            digest, currency=tenant.base_currency, name=membership.user.first_name or ""
        )
        html = render_digest_html(
            digest, currency=tenant.base_currency, name=membership.user.first_name or ""
        )
        try:
            message = EmailMultiAlternatives(
                subject=f"Your week ahead — {digest['as_of']:%-d %b}",
                body=text,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "reports@ledgerflow.app"),
                to=[membership.user.email],
            )
            message.attach_alternative(html, "text/html")
            message.send(fail_silently=False)
            sent += 1
        except Exception as exc:  # noqa: BLE001 — one address must not stop the workspace
            logger.warning("weekly digest to %s failed: %s", membership.user_id, exc)
    return sent
