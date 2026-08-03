from __future__ import annotations

from django.urls import path

from .views import (
    NotificationPreferenceView,
    NotificationReadAllView,
    NotificationReadView,
    NotificationView,
    PushPublicKeyView,
    PushSubscribeView,
    PushUnsubscribeView,
)

urlpatterns = [
    path("", NotificationView.as_view(), name="notification-list"),
    path("preferences/", NotificationPreferenceView.as_view(), name="notification-preferences"),
    path("read-all/", NotificationReadAllView.as_view(), name="notification-read-all"),
    path("<uuid:notification_id>/read/", NotificationReadView.as_view(), name="notification-read"),
    path("push/public-key/", PushPublicKeyView.as_view(), name="push-public-key"),
    path("push/subscribe/", PushSubscribeView.as_view(), name="push-subscribe"),
    path("push/unsubscribe/", PushUnsubscribeView.as_view(), name="push-unsubscribe"),
]
