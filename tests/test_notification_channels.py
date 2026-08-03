"""Email delivery, preferences, and the monthly summary."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from django.core import mail
from django.db import transaction

from apps.notifications import services
from apps.notifications.email_channel import EMAIL_WORTHY, wants_email
from apps.notifications.models import NotificationPreference, NotificationType
from apps.notifications.summary import build_summary, render_summary_text
from apps.common.rls import bind_db_tenant
from apps.common.tenant_context import use_tenant
from tests.conftest import _bearer_client
from tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


@contextmanager
def _tenant(membership):
    """Bind a tenant the way the API layer does.

    Notification preferences are tenant-scoped, so the helpers under test
    cannot be called bare — which is itself the property that made the Celery
    task need an explicit tenant_id.
    """
    with transaction.atomic():
        bind_db_tenant(membership.tenant_id)
        with use_tenant(membership.tenant_id, actor_id=membership.user_id):
            yield


def _pref(user, **kw):
    pref, _ = NotificationPreference.objects.get_or_create(user=user)
    for k, v in kw.items():
        setattr(pref, k, v)
    pref.save()
    return pref


# =============================================================== opt-in rules
def test_email_is_off_until_the_user_asks_for_it():
    """A finance app that emails uninvited gets filtered to spam — taking the
    bill reminders with it."""
    m = MembershipFactory()
    with _tenant(m):
        assert wants_email(user=m.user, notification_type=NotificationType.BILL_DUE) is False


def test_enabling_email_sends_only_the_types_worth_interrupting_for():
    m = MembershipFactory()
    with _tenant(m):
        _pref(m.user, email_enabled=True)
        assert wants_email(user=m.user, notification_type=NotificationType.BILL_DUE) is True
        assert wants_email(user=m.user, notification_type=NotificationType.LOW_BALANCE) is True
        # Informational: pleasant in-app, noise in an inbox.
        assert wants_email(user=m.user, notification_type=NotificationType.GOAL_MILESTONE) is False


def test_an_explicit_type_list_overrides_the_default():
    m = MembershipFactory()
    with _tenant(m):
        _pref(m.user, email_enabled=True, email_types=[NotificationType.GOAL_MILESTONE])
        assert wants_email(user=m.user, notification_type=NotificationType.GOAL_MILESTONE) is True
        assert wants_email(user=m.user, notification_type=NotificationType.BILL_DUE) is False


def test_muting_a_type_mutes_it_everywhere():
    """A type you don't want in-app is certainly not one you want emailed."""
    m = MembershipFactory()
    with _tenant(m):
        _pref(m.user, email_enabled=True, muted_types=[NotificationType.BILL_DUE])
        assert wants_email(user=m.user, notification_type=NotificationType.BILL_DUE) is False


def test_the_default_email_set_is_deadline_or_loss_shaped():
    assert NotificationType.BILL_DUE in EMAIL_WORTHY
    assert NotificationType.LOW_BALANCE in EMAIL_WORTHY
    assert NotificationType.GOAL_MILESTONE not in EMAIL_WORTHY
    assert NotificationType.LARGE_TRANSACTION not in EMAIL_WORTHY


# ================================================================== delivery
def test_an_alert_reaches_the_inbox_when_opted_in(django_capture_on_commit_callbacks):
    m = MembershipFactory()
    with _tenant(m):
        _pref(m.user, email_enabled=True)
    mail.outbox.clear()

    with _tenant(m), django_capture_on_commit_callbacks(execute=True):
        services.raise_notification(
            type=NotificationType.BILL_DUE,
            title="Electricity bill due tomorrow",
            body="KES 3,400 to Kenya Power",
            user=m.user,
            dedupe_key="bill:1",
        )

    assert len(mail.outbox) == 1
    assert "Electricity bill due tomorrow" in mail.outbox[0].subject
    assert m.user.email in mail.outbox[0].to


def test_nothing_is_emailed_without_opt_in(django_capture_on_commit_callbacks):
    m = MembershipFactory()
    mail.outbox.clear()
    with _tenant(m), django_capture_on_commit_callbacks(execute=True):
        services.raise_notification(
            type=NotificationType.BILL_DUE, title="Due", user=m.user, dedupe_key="bill:2"
        )
    assert mail.outbox == []


def test_email_is_queued_after_commit_not_during(django_capture_on_commit_callbacks):
    """The same race that silently swallowed invitation emails."""
    m = MembershipFactory()
    with _tenant(m):
        _pref(m.user, email_enabled=True)
    mail.outbox.clear()

    with _tenant(m), django_capture_on_commit_callbacks(execute=True) as callbacks:
        services.raise_notification(
            type=NotificationType.LOW_BALANCE, title="Low balance", user=m.user, dedupe_key="lb:1"
        )
    assert callbacks, "delivery was not deferred to on_commit"
    assert len(mail.outbox) == 1


def test_a_notification_is_never_emailed_twice(django_capture_on_commit_callbacks):
    from apps.notifications.email_channel import send_notification_email

    m = MembershipFactory()
    with _tenant(m):
        _pref(m.user, email_enabled=True)
    with _tenant(m), django_capture_on_commit_callbacks(execute=True):
        n = services.raise_notification(
            type=NotificationType.BILL_DUE, title="Due", user=m.user, dedupe_key="bill:3"
        )
    mail.outbox.clear()
    with _tenant(m):
        n.refresh_from_db()
        assert send_notification_email(notification=n) is False
    assert mail.outbox == []


def test_a_failing_mail_provider_does_not_break_the_alert(monkeypatch):
    """The in-app inbox is the durable channel; email is best-effort."""
    from apps.notifications import email_channel

    m = MembershipFactory()
    monkeypatch.setattr(
        email_channel.EmailMultiAlternatives, "send",
        lambda self, **kw: (_ for _ in ()).throw(RuntimeError("smtp down")),
    )
    with _tenant(m):
        _pref(m.user, email_enabled=True)
        n = services.raise_notification(
            type=NotificationType.BILL_DUE, title="Due", user=m.user, dedupe_key="bill:4"
        )
        assert n is not None
        assert email_channel.send_notification_email(notification=n) is False


# =============================================================== preferences
def test_preferences_default_to_everything_on_except_email():
    m = MembershipFactory()
    body = _bearer_client(m.user, tenant_id=m.tenant_id).get(
        "/api/v1/notifications/preferences/"
    ).json()

    assert body["email_enabled"] is False
    assert body["push_enabled"] is True
    assert body["muted_types"] == []
    # The type catalogue ships with the payload so the UI can't drift from it.
    assert len(body["available_types"]) == len(NotificationType.choices)


def test_a_single_switch_can_be_patched_without_the_rest():
    m = MembershipFactory()
    client = _bearer_client(m.user, tenant_id=m.tenant_id)
    body = client.patch(
        "/api/v1/notifications/preferences/",
        {"muted_types": [NotificationType.LARGE_TRANSACTION]},
        format="json",
    ).json()

    assert body["muted_types"] == [NotificationType.LARGE_TRANSACTION]
    assert body["push_enabled"] is True  # untouched


def test_an_unknown_notification_type_is_rejected():
    m = MembershipFactory()
    response = _bearer_client(m.user, tenant_id=m.tenant_id).patch(
        "/api/v1/notifications/preferences/", {"muted_types": ["made_up"]}, format="json"
    )
    assert response.status_code == 400


def test_preferences_are_per_user_not_per_workspace():
    owner = MembershipFactory()
    other = MembershipFactory(tenant=owner.tenant)
    _bearer_client(owner.user, tenant_id=owner.tenant_id).patch(
        "/api/v1/notifications/preferences/", {"email_enabled": True}, format="json"
    )
    body = _bearer_client(other.user, tenant_id=other.tenant_id).get(
        "/api/v1/notifications/preferences/"
    ).json()
    assert body["email_enabled"] is False


# ============================================================ monthly summary
def test_the_summary_leads_with_a_verdict():
    text = render_summary_text(
        {
            "month_label": "June 2026",
            "income_minor": 500_000,
            "spending_minor": 320_000,
            "net_minor": 180_000,
            "net_worth_minor": 2_400_000,
        },
        currency="KES",
        name="Amina",
    )
    assert "Hi Amina" in text
    # The verdict is the only line most people read, so it comes first.
    assert text.index("put aside") < text.index("Money in")
    assert "unsubscribe" in text.lower() or "Turn them off" in text


def test_the_summary_names_a_shortfall_plainly():
    text = render_summary_text(
        {"month_label": "June 2026", "income_minor": 100, "spending_minor": 400,
         "net_minor": -300, "net_worth_minor": None},
        currency="USD",
    )
    assert "more than you earned" in text


def test_a_dormant_workspace_gets_no_summary():
    """'You earned 0 and spent 0' is a reason to unsubscribe."""
    from apps.notifications.summary import send_monthly_summary_for_tenant

    m = MembershipFactory()
    with _tenant(m):
        _pref(m.user, email_enabled=True, monthly_summary=True)
    mail.outbox.clear()
    # Binds its own tenant context internally, so it is called bare here.
    assert send_monthly_summary_for_tenant(tenant_id=m.tenant_id) == 0
    assert mail.outbox == []
