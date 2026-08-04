from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.api_base import TenantScopedAPIView
from apps.common.pagination import CursorPagination
from apps.tenancy.models import Role
from apps.tenancy.permissions import IsTenantMember

from .. import selectors, services
from ..models import Notification, NotificationPreference, NotificationType


def _out(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "severity": n.severity,
        "title": n.title,
        "body": n.body,
        "subject_type": n.subject_type,
        "subject_id": n.subject_id,
        "data": n.data,
        "read_at": n.read_at,
        "created_at": n.created_at,
    }


class NotificationView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None
    pagination_class = CursorPagination

    def get(self, request):
        unread_only = request.query_params.get("unread", "").lower() in ("1", "true", "yes")
        qs = selectors.inbox(user=request.user, unread_only=unread_only)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        resp = paginator.get_paginated_response([_out(n) for n in page])
        resp.data["unread_count"] = selectors.unread_count(user=request.user)
        return resp


class NotificationReadView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER  # reading your own notices is not a write on finances
    serializer_class = None

    def post(self, request, notification_id):
        n = Notification.objects.filter(id=notification_id).first()
        if n is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        services.mark_read(notification=n)
        return Response(_out(n))


class NotificationReadAllView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def post(self, request):
        count = services.mark_all_read(user=request.user)
        return Response({"marked_read": count})


# --------------------------------------------------------------- push subscriptions
class PushSubscribeSerializer(serializers.Serializer):
    """Mirrors the browser's `PushSubscription.toJSON()` shape directly, so
    the frontend can forward it with no reshaping."""

    endpoint = serializers.URLField(max_length=1024)

    class KeysSerializer(serializers.Serializer):
        p256dh = serializers.CharField()
        auth = serializers.CharField()

    keys = KeysSerializer()
    user_agent = serializers.CharField(required=False, allow_blank=True, default="")


class PushSubscribeView(TenantScopedAPIView, APIView):
    """Register this browser for push. Called right after
    `PushManager.subscribe()` resolves in the frontend."""

    permission_classes = [IsTenantMember]
    serializer_class = PushSubscribeSerializer

    def post(self, request):
        s = PushSubscribeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data
        subscription = services.subscribe_to_push(
            user=request.user,
            endpoint=v["endpoint"],
            p256dh_key=v["keys"]["p256dh"],
            auth_key=v["keys"]["auth"],
            user_agent=v.get("user_agent", ""),
        )
        return Response({"id": subscription.id}, status=status.HTTP_201_CREATED)


class PushUnsubscribeView(TenantScopedAPIView, APIView):
    permission_classes = [IsTenantMember]
    serializer_class = PushSubscribeSerializer

    def post(self, request):
        endpoint = request.data.get("endpoint")
        if not endpoint:
            return Response({"detail": "endpoint is required."}, status=status.HTTP_400_BAD_REQUEST)
        services.unsubscribe_from_push(endpoint=endpoint)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PushPublicKeyView(TenantScopedAPIView, APIView):
    """The VAPID public key, so the frontend can call
    `PushManager.subscribe({applicationServerKey: ...})`.

    204 when push isn't configured on this deployment, so the frontend can
    hide the "enable notifications" affordance entirely rather than offer a
    button that will always fail.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = None

    def get(self, request):
        from django.conf import settings

        if not settings.VAPID_PUBLIC_KEY:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response({"public_key": settings.VAPID_PUBLIC_KEY})


class NotificationPreferenceSerializer(serializers.Serializer):
    """Read/write shape for a user's alert preferences.

    Every field optional so a client can PATCH one switch without round-tripping
    the whole object — these are toggles a user flips one at a time.
    """

    muted_types = serializers.ListField(
        child=serializers.ChoiceField(choices=NotificationType.values), required=False
    )
    email_enabled = serializers.BooleanField(required=False)
    email_types = serializers.ListField(
        child=serializers.ChoiceField(choices=NotificationType.values), required=False
    )
    push_enabled = serializers.BooleanField(required=False)
    monthly_summary = serializers.BooleanField(required=False)
    weekly_digest = serializers.BooleanField(required=False)
    budget_threshold = serializers.FloatField(required=False, min_value=0.1, max_value=2.0)
    low_balance_minor = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    large_transaction_minor = serializers.IntegerField(required=False, allow_null=True, min_value=0)


class NotificationPreferenceView(TenantScopedAPIView, APIView):
    """A user's own alert preferences.

    The model has supported per-type muting and thresholds since it was written;
    nothing exposed it, so the only control a user had was a master push toggle.
    That is the setting people reach for when alerts get noisy, and "all off"
    was the only answer available — which loses the bill reminders too.

    Preferences are per-user within a workspace, so someone in two households
    can want different alerts in each.
    """

    permission_classes = [IsTenantMember]
    required_role = Role.VIEWER
    serializer_class = NotificationPreferenceSerializer

    #: Types offered by email when the user enables email without choosing.
    def _payload(self, pref: NotificationPreference | None) -> dict:
        from ..email_channel import EMAIL_WORTHY

        return {
            "muted_types": (pref.muted_types if pref else []) or [],
            "email_enabled": bool(pref.email_enabled) if pref else False,
            "email_types": (pref.email_types if pref else []) or [],
            "push_enabled": bool(pref.push_enabled) if pref else True,
            "monthly_summary": bool(pref.monthly_summary) if pref else True,
            "weekly_digest": bool(pref.weekly_digest) if pref else True,
            "budget_threshold": pref.budget_threshold if pref else 0.9,
            "low_balance_minor": pref.low_balance_minor if pref else None,
            "large_transaction_minor": pref.large_transaction_minor if pref else None,
            # The catalogue travels with the payload so the UI never hard-codes
            # a list that can drift from the server's.
            "available_types": [{"value": v, "label": label} for v, label in NotificationType.choices],
            "email_default_types": sorted(str(t) for t in EMAIL_WORTHY),
        }

    def get(self, request):
        pref = NotificationPreference.objects.filter(user=request.user).first()
        return Response(self._payload(pref))

    def patch(self, request):
        payload = NotificationPreferenceSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)

        pref, _ = NotificationPreference.objects.get_or_create(user=request.user)
        for field, value in payload.validated_data.items():
            setattr(pref, field, value)
        pref.save()
        return Response(self._payload(pref))
