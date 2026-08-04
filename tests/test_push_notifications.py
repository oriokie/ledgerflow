"""Push notifications: subscriptions, delivery, and the dispatch wiring.

The property tested hardest is that a push failure never propagates past the
caller trying to raise a notification — a budget alert firing must not 500
because one of a user's devices has gone quiet. Close behind: a subscription
the browser has permanently discarded (410/404) must stop being retried, or
every future notification pays for a send that can never succeed.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.notifications import push, services
from apps.notifications.models import (
    Notification,
    NotificationPreference,
    NotificationType,
    PushSubscription,
)
from tests.utils import tenant_scope

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    return uuid.uuid4()


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create(email="user@example.com")


def _subscribe(user, endpoint="https://push.example.com/abc"):
    return services.subscribe_to_push(
        user=user, endpoint=endpoint, p256dh_key="p256-key", auth_key="auth-key"
    )


class _FakeWebPushException(Exception):
    def __init__(self, status_code):
        self.response = MagicMock(status_code=status_code)


# =============================================================================
# Subscription lifecycle
# =============================================================================
def test_subscribing_creates_a_row(tenant, user):
    with tenant_scope(tenant):
        sub = _subscribe(user)
        assert sub.endpoint == "https://push.example.com/abc"
        assert sub.is_active is True


def test_resubscribing_the_same_endpoint_updates_rather_than_duplicates(tenant, user):
    """The browser hands out one endpoint per registration; re-subscribing
    from the same device — a cleared cache, a reinstalled PWA — must not pile
    up a duplicate that silently goes stale."""
    with tenant_scope(tenant):
        _subscribe(user)
        _subscribe(user)
        assert PushSubscription.objects.count() == 1


def test_resubscribing_clears_an_expired_flag(tenant, user):
    """A fresh subscribe from the browser is proof the endpoint works again."""
    with tenant_scope(tenant):
        sub = _subscribe(user)
        sub.expired_at = timezone.now()
        sub.save()

        _subscribe(user)
        sub.refresh_from_db()
        assert sub.is_active is True


def test_unsubscribing_removes_the_row(tenant, user):
    with tenant_scope(tenant):
        _subscribe(user)
        assert services.unsubscribe_from_push(endpoint="https://push.example.com/abc") is True
        assert PushSubscription.objects.count() == 0


def test_resubscribing_after_unsubscribing_does_not_collide(tenant, user):
    """Regression: PushSubscription is soft-deletable, and its unique
    constraint on `endpoint` must exclude soft-deleted rows — the same trap
    caught earlier on DebtProfile's rate-history constraint. Without the
    exclusion, unsubscribing then re-subscribing the same browser collides
    with a unique constraint on a row the alive-only manager can no longer see,
    making "turn notifications back on" a 500."""
    with tenant_scope(tenant):
        _subscribe(user)
        services.unsubscribe_from_push(endpoint="https://push.example.com/abc")

        resubscribed = _subscribe(user)
        assert resubscribed.is_active is True
        assert PushSubscription.objects.filter(endpoint="https://push.example.com/abc").count() == 1


def test_unsubscribing_twice_is_a_no_op_not_an_error(tenant, user):
    with tenant_scope(tenant):
        _subscribe(user)
        services.unsubscribe_from_push(endpoint="https://push.example.com/abc")
        assert services.unsubscribe_from_push(endpoint="https://push.example.com/abc") is False


def test_a_user_can_have_several_subscriptions(tenant, user):
    """A phone and a laptop both subscribed is the normal case."""
    with tenant_scope(tenant):
        _subscribe(user, endpoint="https://push.example.com/phone")
        _subscribe(user, endpoint="https://push.example.com/laptop")
        assert PushSubscription.objects.filter(user=user).count() == 2


# =============================================================================
# vapid_configured — the optional-infrastructure gate
# =============================================================================
def test_push_is_unconfigured_by_default(settings):
    settings.VAPID_PRIVATE_KEY = ""
    settings.VAPID_CLAIMS_EMAIL = ""
    assert push.vapid_configured() is False


def test_push_is_configured_once_both_values_are_set(settings):
    settings.VAPID_PRIVATE_KEY = "some-key"
    settings.VAPID_CLAIMS_EMAIL = "ops@example.com"
    assert push.vapid_configured() is True


def test_sending_without_configuration_is_a_no_op_not_an_error(tenant, user, settings):
    settings.VAPID_PRIVATE_KEY = ""
    with tenant_scope(tenant):
        sub = _subscribe(user)
        assert push.send_to_subscription(subscription=sub, payload={"title": "x"}) is False


# =============================================================================
# Sending — mocked pywebpush, since the real service is a third party
# =============================================================================
def test_a_successful_send_updates_last_used(tenant, user, settings):
    settings.VAPID_PRIVATE_KEY = "key"
    settings.VAPID_CLAIMS_EMAIL = "ops@example.com"
    with tenant_scope(tenant):
        sub = _subscribe(user)
        with patch("pywebpush.webpush") as mocked:
            mocked.return_value = None
            result = push.send_to_subscription(subscription=sub, payload={"title": "Hi"})
        assert result is True
        sub.refresh_from_db()
        assert sub.last_used_at is not None


def test_a_410_permanently_expires_the_subscription(tenant, user, settings):
    """The browser discarded this registration; retrying it is not a
    transient failure to recover from."""
    settings.VAPID_PRIVATE_KEY = "key"
    settings.VAPID_CLAIMS_EMAIL = "ops@example.com"
    with tenant_scope(tenant):
        sub = _subscribe(user)
        with patch("pywebpush.webpush") as mocked, patch("pywebpush.WebPushException", _FakeWebPushException):
            mocked.side_effect = _FakeWebPushException(410)
            result = push.send_to_subscription(subscription=sub, payload={"title": "Hi"})
        assert result is False
        sub.refresh_from_db()
        assert sub.is_active is False


def test_a_transient_failure_does_not_expire_the_subscription(tenant, user, settings):
    """A 503 is the push service having a bad moment, not the browser telling
    us to stop — expiring on every wobble would silence a working device."""
    settings.VAPID_PRIVATE_KEY = "key"
    settings.VAPID_CLAIMS_EMAIL = "ops@example.com"
    with tenant_scope(tenant):
        sub = _subscribe(user)
        with patch("pywebpush.webpush") as mocked, patch("pywebpush.WebPushException", _FakeWebPushException):
            mocked.side_effect = _FakeWebPushException(503)
            push.send_to_subscription(subscription=sub, payload={"title": "Hi"})
        sub.refresh_from_db()
        assert sub.is_active is True


def test_an_unexpected_exception_never_propagates(tenant, user, settings):
    """A push failure must never break the caller raising an underlying
    notification — a budget alert firing shouldn't 500 because a device
    went offline."""
    settings.VAPID_PRIVATE_KEY = "key"
    settings.VAPID_CLAIMS_EMAIL = "ops@example.com"
    with tenant_scope(tenant):
        sub = _subscribe(user)
        with patch("pywebpush.webpush", side_effect=RuntimeError("network exploded")):
            result = push.send_to_subscription(subscription=sub, payload={"title": "Hi"})
        assert result is False


def test_an_expired_subscription_is_never_sent_to(tenant, user, settings):
    settings.VAPID_PRIVATE_KEY = "key"
    settings.VAPID_CLAIMS_EMAIL = "ops@example.com"
    with tenant_scope(tenant):
        sub = _subscribe(user)
        sub.expired_at = timezone.now()
        sub.save()

        notification = Notification.objects.create(
            user=user, type=NotificationType.LOW_BALANCE, title="Low balance"
        )
        with patch("pywebpush.webpush") as mocked:
            delivered = push.push_notification(notification)
        assert delivered == 0
        mocked.assert_not_called()


# =============================================================================
# push_notification — fan-out to every active device
# =============================================================================
def test_push_notification_reaches_every_active_device(tenant, user, settings):
    settings.VAPID_PRIVATE_KEY = "key"
    settings.VAPID_CLAIMS_EMAIL = "ops@example.com"
    with tenant_scope(tenant):
        _subscribe(user, endpoint="https://push.example.com/phone")
        _subscribe(user, endpoint="https://push.example.com/laptop")
        notification = Notification.objects.create(
            user=user, type=NotificationType.LOW_BALANCE, title="Low balance"
        )
        with patch("pywebpush.webpush") as mocked:
            mocked.return_value = None
            delivered = push.push_notification(notification)
        assert delivered == 2


def test_a_delivered_push_is_recorded_on_the_notification(tenant, user, settings):
    settings.VAPID_PRIVATE_KEY = "key"
    settings.VAPID_CLAIMS_EMAIL = "ops@example.com"
    with tenant_scope(tenant):
        _subscribe(user)
        notification = Notification.objects.create(
            user=user,
            type=NotificationType.LOW_BALANCE,
            title="Low balance",
            delivered_channels=["inapp"],
        )
        with patch("pywebpush.webpush") as mocked:
            mocked.return_value = None
            push.push_notification(notification)
        notification.refresh_from_db()
        assert "push" in notification.delivered_channels
        assert "inapp" in notification.delivered_channels


def test_push_respects_the_users_master_switch(tenant, user, settings):
    """A user who wants push off entirely, independent of individual muted
    types, must actually get nothing — not just fewer things."""
    settings.VAPID_PRIVATE_KEY = "key"
    settings.VAPID_CLAIMS_EMAIL = "ops@example.com"
    with tenant_scope(tenant):
        _subscribe(user)
        NotificationPreference.objects.create(user=user, push_enabled=False)
        notification = Notification.objects.create(
            user=user, type=NotificationType.LOW_BALANCE, title="Low balance"
        )
        with patch("pywebpush.webpush") as mocked:
            delivered = push.push_notification(notification)
        assert delivered == 0
        mocked.assert_not_called()


def test_a_workspace_wide_notification_with_no_user_sends_no_push(tenant, settings):
    """Nothing to address a push to — a workspace notice with `user=None`."""
    settings.VAPID_PRIVATE_KEY = "key"
    settings.VAPID_CLAIMS_EMAIL = "ops@example.com"
    with tenant_scope(tenant):
        notification = Notification.objects.create(
            user=None, type=NotificationType.LOW_BALANCE, title="Workspace notice"
        )
        assert push.push_notification(notification) == 0


# =============================================================================
# raise_notification dispatch wiring
# =============================================================================
def test_raising_a_notification_schedules_a_push_dispatch(tenant, user, django_capture_on_commit_callbacks):
    """The single choke point every producer passes through — this is what
    stops five different producers each needing to remember to wire push in
    for themselves."""
    with tenant_scope(tenant):
        with django_capture_on_commit_callbacks() as callbacks:
            from apps.notifications import services as notif_services

            notif_services.raise_notification(
                type=NotificationType.LOW_BALANCE, title="Low balance", user=user
            )
        assert callbacks, "no push dispatch was scheduled by raise_notification"


def test_refreshing_an_existing_dedupe_does_not_re_dispatch_push(
    tenant, user, django_capture_on_commit_callbacks
):
    """A budget alert nudging from 90% to 105% is the same underlying alert —
    re-buzzing a phone on every refresh would be closer to spam than a
    notification."""
    with tenant_scope(tenant):
        from apps.notifications import services as notif_services

        with django_capture_on_commit_callbacks():
            notif_services.raise_notification(
                type=NotificationType.BUDGET_THRESHOLD,
                title="90% of budget",
                user=user,
                dedupe_key="budget:groceries:2026-06",
            )
        with django_capture_on_commit_callbacks() as callbacks:
            notif_services.raise_notification(
                type=NotificationType.BUDGET_THRESHOLD,
                title="105% of budget",
                user=user,
                dedupe_key="budget:groceries:2026-06",
            )
        assert not callbacks


def test_a_muted_type_raises_nothing_and_schedules_no_push(tenant, user):
    with tenant_scope(tenant):
        from apps.notifications import services as notif_services

        NotificationPreference.objects.create(user=user, muted_types=[NotificationType.LOW_BALANCE])
        result = notif_services.raise_notification(
            type=NotificationType.LOW_BALANCE, title="Low balance", user=user
        )
        assert result is None


# =============================================================================
# API
# =============================================================================
def test_api_subscribe_and_unsubscribe(tenant_context):
    _, client = tenant_context
    resp = client.post(
        "/api/v1/notifications/push/subscribe/",
        {
            "endpoint": "https://push.example.com/browser",
            "keys": {"p256dh": "abc", "auth": "def"},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data

    unsub = client.post(
        "/api/v1/notifications/push/unsubscribe/",
        {"endpoint": "https://push.example.com/browser"},
        format="json",
    )
    assert unsub.status_code == 204


def test_api_public_key_is_204_when_unconfigured(tenant_context, settings):
    settings.VAPID_PUBLIC_KEY = ""
    _, client = tenant_context
    resp = client.get("/api/v1/notifications/push/public-key/")
    assert resp.status_code == 204


def test_api_public_key_is_returned_when_configured(tenant_context, settings):
    settings.VAPID_PUBLIC_KEY = "a-public-key"
    _, client = tenant_context
    resp = client.get("/api/v1/notifications/push/public-key/")
    assert resp.status_code == 200
    assert resp.data["public_key"] == "a-public-key"
