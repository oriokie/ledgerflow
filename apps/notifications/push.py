"""Web Push delivery.

Standards-based, no vendor SDK: any browser that implements the Push API can
receive from this without a proprietary client library or a per-platform
integration. The VAPID keypair (`py_vapid`) is this server's identity to the
push services (Chrome talks to Google's endpoint, Firefox to Mozilla's, etc.)
— it proves messages came from us, not that any particular push service
trusts us in advance.

Two things this module is careful never to do:

**Never raise past a caller who's trying to notify someone.** A push failure
must not break the underlying event — a budget alert firing shouldn't 500
because one of a user's three devices went offline last month. Every send is
best-effort and logged.

**Never keep retrying a subscription the browser has discarded.** A 404 or 410
from the push service means the browser un-registered it — permanently, not
transiently. Retrying that forever wastes calls and never succeeds; the
subscription is marked expired instead, which is the same "reversible,
recorded, not silent" discipline as everything else optional in this product.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.utils import timezone

from .models import Notification, PushSubscription

logger = logging.getLogger("ledgerflow.notifications.push")


class PushError(Exception): ...


def vapid_configured() -> bool:
    """Whether the server has a VAPID identity to send with at all.

    Push is optional infrastructure exactly like the coach's LLM providers:
    the product works with it off, and every caller checks this first rather
    than discovering a missing key by way of an exception.
    """
    return bool(getattr(settings, "VAPID_PRIVATE_KEY", "") and getattr(settings, "VAPID_CLAIMS_EMAIL", ""))


def _vapid_claims() -> dict:
    email = getattr(settings, "VAPID_CLAIMS_EMAIL", "")
    return {"sub": f"mailto:{email}"}


def send_to_subscription(*, subscription: PushSubscription, payload: dict) -> bool:
    """Send one payload to one subscription. Returns whether it was delivered.

    Never raises. A push endpoint is a third-party service outside this
    product's control, and its failures are exactly as routine as a phone
    being switched off — logged, not propagated.
    """
    if not vapid_configured():
        return False

    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh_key, "auth": subscription.auth_key},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims=_vapid_claims(),
        )
        subscription.last_used_at = timezone.now()
        subscription.save(update_fields=["last_used_at", "updated_at"])
        return True
    except WebPushException as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code in (404, 410):
            # The browser has discarded this registration. Retrying is not a
            # transient failure to recover from — it will never succeed again.
            subscription.expired_at = timezone.now()
            subscription.save(update_fields=["expired_at", "updated_at"])
            logger.info("push subscription expired: %s", subscription.id)
        else:
            logger.warning("push send failed (%s): %s", status_code, exc)
        return False
    except Exception:  # pragma: no cover - defensive; must never break the caller
        logger.exception("unexpected push send failure")
        return False


def _notification_payload(notification: Notification) -> dict:
    return {
        "title": notification.title,
        "body": notification.body,
        "tag": notification.dedupe_key or str(notification.id),
        "data": {
            "notification_id": str(notification.id),
            "subject_type": notification.subject_type,
            "subject_id": str(notification.subject_id) if notification.subject_id else None,
        },
    }


def push_notification(notification: Notification) -> int:
    """Deliver one notification to every active subscription its recipient has.

    Called from `raise_notification`'s single choke point, the same pattern as
    the ledger dispatching cache invalidation from `post_journal_entry` — every
    caller that creates a notification gets push delivery for free rather than
    each producer having to remember to wire it in.

    Returns the number of devices actually reached, purely for logging; the
    caller (a Celery task) doesn't act on the count.
    """
    if notification.user_id is None or not vapid_configured():
        return 0

    from .models import NotificationPreference

    pref = NotificationPreference.objects.filter(user_id=notification.user_id).first()
    if pref and not pref.push_enabled:
        return 0

    subscriptions = PushSubscription.objects.filter(
        user_id=notification.user_id, expired_at__isnull=True
    )
    payload = _notification_payload(notification)
    delivered = sum(
        1 for sub in subscriptions if send_to_subscription(subscription=sub, payload=payload)
    )
    if delivered:
        channels = set(notification.delivered_channels or [])
        channels.add("push")
        notification.delivered_channels = sorted(channels)
        notification.save(update_fields=["delivered_channels", "updated_at"])
    return delivered
