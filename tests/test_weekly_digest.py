"""The weekly money digest — the Monday note.

The properties worth pinning: it leads with the figure that changes what
someone does today, an all-quiet workspace sends nothing (the one Monday that
matters must not be filtered with fifty silent ones), and the opt-in gates are
honoured exactly.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.core import mail
from django.test import override_settings
from django.utils import timezone

from apps.finance import services as finance_services
from apps.finance.bills import create_bill
from apps.finance.models import AccountType, CategoryKind
from apps.notifications import digest
from apps.notifications.models import NotificationPreference
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


def _account(opening=500_000):
    return finance_services.create_financial_account(
        name="Checking", account_type=AccountType.CHECKING, currency="USD", opening_balance_minor=opening
    )


def _spend_last_week(account, amount=25_000):
    category = finance_services.create_category(name="Groceries", kind=CategoryKind.EXPENSE, currency="USD")
    when = timezone.now() - timedelta(days=3)
    finance_services.record_expense(
        financial_account=account, category=category, amount_minor=amount, occurred_at=when
    )


# ------------------------------------------------------------------ building
def test_the_digest_measures_last_weeks_flows(tenant):
    with tenant_scope(tenant):
        account = _account()
        _spend_last_week(account, 25_000)
        built = digest.build_digest(base_currency="USD")

    assert built["outflow_minor"] == 25_000
    assert built["inflow_minor"] == 0


def test_the_digest_carries_the_same_safe_to_spend_as_the_dashboard(tenant):
    """One definition of the number, everywhere. The digest must read the
    calendar's trough, not derive its own arithmetic."""
    from apps.finance import cashflow_calendar as cc

    with tenant_scope(tenant):
        _account(opening=500_000)
        built = digest.build_digest(base_currency="USD")
        calendar = cc.cashflow_calendar(days=35, currency="USD")

    assert built["safe_to_spend_minor"] == calendar.safe_to_spend_minor


def test_bills_due_within_the_week_are_listed(tenant):
    with tenant_scope(tenant):
        _account()
        create_bill(
            name="Rent",
            amount_minor=100_000,
            currency="USD",
            due_on=timezone.localdate() + timedelta(days=3),
        )
        create_bill(
            name="Insurance",
            amount_minor=30_000,
            currency="USD",
            due_on=timezone.localdate() + timedelta(days=20),  # beyond the week
        )
        built = digest.build_digest(base_currency="USD")

    names = [bill["name"] for bill in built["bills"]]
    assert names == ["Rent"]


# ----------------------------------------------------------------- rendering
def test_safe_to_spend_leads_the_email(tenant):
    """It is the one figure that changes what someone does today — which is
    the entire argument for a weekly cadence."""
    with tenant_scope(tenant):
        account = _account()
        _spend_last_week(account)
        built = digest.build_digest(base_currency="USD")

    text = digest.render_digest_text(built, currency="USD", name="Edwin")
    body_lines = [line for line in text.splitlines() if line.strip()]
    assert body_lines[0] == "Hi Edwin,"
    assert body_lines[1].startswith("Safe to spend:")


def test_the_unsubscribe_path_is_always_present(tenant):
    with tenant_scope(tenant):
        account = _account()
        _spend_last_week(account)
        built = digest.build_digest(base_currency="USD")

    assert "Turn it off here" in digest.render_digest_text(built, currency="USD")


# ------------------------------------------------------------------- sending
def _opted_in_member(tenant_context):
    membership, _ = tenant_context
    with tenant_scope(membership.tenant_id):
        NotificationPreference.objects.create(user=membership.user, email_enabled=True, weekly_digest=True)
    return membership


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_an_opted_in_member_receives_the_digest(tenant_context):
    membership = _opted_in_member(tenant_context)
    with tenant_scope(membership.tenant_id):
        account = _account()
        _spend_last_week(account)

    sent = digest.send_weekly_digest_for_tenant(tenant_id=membership.tenant_id)

    assert sent == 1
    assert len(mail.outbox) == 1
    assert "week ahead" in mail.outbox[0].subject


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_an_all_quiet_workspace_sends_nothing(tenant_context):
    """ "All quiet" every Monday is how the one Monday that matters gets
    filtered with the rest."""
    membership = _opted_in_member(tenant_context)
    with tenant_scope(membership.tenant_id):
        _account()  # an account, but nothing moved, nothing due, nothing found

    sent = digest.send_weekly_digest_for_tenant(tenant_id=membership.tenant_id)

    assert sent == 0
    assert mail.outbox == []


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_email_disabled_wins_over_the_digest_preference(tenant_context):
    """weekly_digest=True with email_enabled=False must send nothing — the
    master switch is the user's statement that email is unwelcome."""
    membership, _ = tenant_context
    with tenant_scope(membership.tenant_id):
        NotificationPreference.objects.create(user=membership.user, email_enabled=False, weekly_digest=True)
        account = _account()
        _spend_last_week(account)

    sent = digest.send_weekly_digest_for_tenant(tenant_id=membership.tenant_id)

    assert sent == 0
    assert mail.outbox == []


def test_the_task_is_scheduled_for_monday_morning_after_the_coach():
    from django.conf import settings

    entry = settings.CELERY_BEAT_SCHEDULE["notifications-weekly-digest"]
    assert entry["task"] == "notifications.send_weekly_digests"
    schedule = entry["schedule"]
    assert schedule.day_of_week == {1}
    # After the 05:30 coach run, so "worth a look" carries fresh findings.
    assert min(schedule.hour) > 5


# ---------------------------------------------------------------------- html
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_the_email_carries_an_html_alternative_and_keeps_the_text(tenant_context):
    """HTML is presentation; text is the copy that survives everything —
    screen readers, strict filters, reply quoting. Both must ship."""
    membership = _opted_in_member(tenant_context)
    with tenant_scope(membership.tenant_id):
        account = _account()
        _spend_last_week(account)

    digest.send_weekly_digest_for_tenant(tenant_id=membership.tenant_id)

    message = mail.outbox[0]
    assert message.body.startswith("Hi")  # plain text intact
    html, mime = message.alternatives[0]
    assert mime == "text/html"
    assert "Safe to spend" in message.body
    assert "safe to spend" in html
    assert "LedgerFlow" in html


def test_html_escapes_whatever_the_ledger_contains(tenant):
    """Bill names are user input. A bill called <script> must render as text,
    not execute in whatever preview pane is rendering the message."""
    built = {
        "as_of": timezone.localdate(),
        "inflow_minor": 0,
        "outflow_minor": 5_000,
        "safe_to_spend_minor": 10_000,
        "first_negative_on": None,
        "bills": [
            {
                "name": '<script>alert("pwn")</script>',
                "amount_minor": 1_000,
                "due_on": timezone.localdate(),
            }
        ],
        "findings": [],
    }
    html = digest.render_digest_html(built, currency="USD")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_the_preheader_is_the_figure_not_a_description(tenant):
    """The preheader decides the open. It must carry the number, because that
    is the reason the email exists."""
    with tenant_scope(tenant):
        account = _account(opening=500_000)
        _spend_last_week(account)
        built = digest.build_digest(base_currency="USD")

    html = digest.render_digest_html(built, currency="USD")
    assert "Safe to spend: USD" in html
