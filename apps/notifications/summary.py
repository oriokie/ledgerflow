"""The monthly summary email.

Every report in this product is pull-only: the user must remember to come and
look. That makes the analytics worth less than they should be, because the
people who most need a monthly review are exactly the people who do not perform
one unprompted.

This is deliberately a *summary*, not a report. Four figures and a single
comparison, because an email that tries to reproduce the dashboard gets skimmed
and then filtered. The job is to answer "was last month fine?" in the preview
pane, and to give someone a reason to open the app when the answer is no.

All figures come from existing selectors — nothing here computes anything new,
which is also why it stays correct as those selectors improve.
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

logger = logging.getLogger("ledgerflow.notifications.summary")


def _previous_month(today: date) -> tuple[date, date]:
    """First and last day of the month before `today`."""
    first_of_this = today.replace(day=1)
    last_of_prev = first_of_this - timedelta(days=1)
    return last_of_prev.replace(day=1), last_of_prev


def build_summary(*, tenant_id, base_currency: str, as_of: date | None = None) -> dict:
    """Gather the month's headline figures for one workspace.

    Must be called inside a bound tenant context — the selectors it uses are
    tenant-scoped, and binding here rather than inside would hide that from
    the caller.
    """
    from apps.finance import selectors as finance

    as_of = as_of or timezone.localdate()
    start, end = _previous_month(as_of)

    # `cash_flow` returns one row per currency; the summary reports the
    # workspace's base currency only. A multi-currency household gets a figure
    # it can act on rather than a sum across incomparable units — the same
    # reasoning the platform metrics use for MRR.
    from datetime import datetime, time

    start_dt = datetime.combine(start, time.min, tzinfo=timezone.get_current_timezone())
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.get_current_timezone())

    income = spending = 0
    try:
        for row in finance.cash_flow(start=start_dt, end=end_dt):
            if row.currency == base_currency:
                income, spending = row.income_minor, row.expense_minor
                break
    except Exception:  # noqa: BLE001 — a summary must not fail on one bad figure
        pass

    try:
        worth = finance.net_worth_in_base(base_currency)
        net_worth = worth.get("net_minor")
    except Exception:  # noqa: BLE001
        net_worth = None

    return {
        "period_start": start,
        "period_end": end,
        "month_label": start.strftime("%B %Y"),
        "income_minor": income,
        "spending_minor": spending,
        "net_minor": income - spending,
        "net_worth_minor": net_worth,
    }


def _money(minor: int | None, currency: str) -> str:
    if minor is None:
        return "—"
    return f"{minor / 100:,.2f} {currency}"


def render_summary_text(summary: dict, *, currency: str, name: str = "") -> str:
    greeting = f"Hi {name}," if name else "Hi,"
    net = summary["net_minor"]
    # The verdict goes first because it is the only line most people read.
    verdict = (
        f"You put aside {_money(net, currency)} in {summary['month_label']}."
        if net > 0
        else f"You spent {_money(abs(net), currency)} more than you earned in {summary['month_label']}."
    )
    lines = [
        greeting,
        "",
        verdict,
        "",
        f"  Money in    {_money(summary['income_minor'], currency)}",
        f"  Money out   {_money(summary['spending_minor'], currency)}",
        f"  Net         {_money(net, currency)}",
    ]
    if summary["net_worth_minor"] is not None:
        lines.append(f"  Net worth   {_money(summary['net_worth_minor'], currency)}")
    lines += [
        "",
        f"See the detail: {build('reports')}",
        "",
        f"Don't want these? Turn them off here: {build('settings/preferences')}",
    ]
    return "\n".join(lines)


def send_monthly_summary_for_tenant(*, tenant_id, as_of: date | None = None) -> int:
    """Email every opted-in member of one workspace. Returns how many were sent."""
    from apps.tenancy.models import Membership, Tenant

    from .models import NotificationPreference

    tenant = Tenant.objects.filter(id=tenant_id).first()
    if tenant is None:
        return 0

    with transaction.atomic():
        bind_db_tenant(tenant_id)
        with use_tenant(tenant_id):
            summary = build_summary(tenant_id=tenant_id, base_currency=tenant.base_currency, as_of=as_of)
            # A workspace with no activity gets no email. Sending "you earned 0
            # and spent 0" to someone mid-onboarding is a reason to unsubscribe.
            if not summary["income_minor"] and not summary["spending_minor"]:
                return 0
            opted_in = {
                p.user_id
                for p in NotificationPreference.objects.filter(monthly_summary=True, email_enabled=True)
            }

    sent = 0
    memberships = Membership.objects.filter(tenant_id=tenant_id).select_related("user")
    for membership in memberships:
        if membership.user_id not in opted_in or not membership.user.email:
            continue
        text = render_summary_text(
            summary, currency=tenant.base_currency, name=membership.user.first_name or ""
        )
        try:
            EmailMultiAlternatives(
                subject=f"Your {summary['month_label']} summary",
                body=text,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "reports@ledgerflow.app"),
                to=[membership.user.email],
            ).send(fail_silently=False)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("monthly summary to %s failed: %s", membership.user_id, exc)
    return sent
