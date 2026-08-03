"""Email delivery for notifications.

Alerts previously reached only an in-app inbox and Web Push, which inverted
their purpose: "your electricity bill is due tomorrow" is worth sending
precisely because the recipient is *not* thinking about their finances. Push
does not close that gap — desktop push needs the browser running, and iOS
Safari needs the PWA installed to the home screen, which most people never do.

Three decisions shape this module:

* **Opt-in, not opt-out.** A finance app that emails uninvited gets filtered to
  spam, and the bill reminders go to spam with it. `email_enabled` defaults to
  False; turning it on is the user saying email is welcome.
* **A default worth having.** With email on and no explicit type list, only
  `EMAIL_WORTHY` types are sent — the ones with a deadline or a loss attached.
  Sending all nine would train people to ignore all nine, and the type they
  then miss is the one that mattered.
* **Delivery is recorded, not assumed.** `delivered_channels` is appended after
  a successful send, so a notification never emails twice and the trail shows
  what actually left the building.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from .models import Notification, NotificationPreference, NotificationType

logger = logging.getLogger("ledgerflow.notifications.email")

#: Sent by default when a user enables email without naming types.
#:
#: The test for inclusion is "does missing this cost the user money or a
#: deadline". Goal milestones and large-transaction notices are informational —
#: pleasant in-app, noise in an inbox — so they are opt-in individually.
EMAIL_WORTHY: frozenset[str] = frozenset(
    {
        NotificationType.BILL_DUE,
        NotificationType.BILL_OVERDUE,
        NotificationType.LOW_BALANCE,
        NotificationType.BUDGET_EXCEEDED,
        NotificationType.ANOMALY,
    }
)


def preference_for(user) -> NotificationPreference | None:
    if user is None:
        return None
    return NotificationPreference.objects.filter(user=user).first()


def wants_email(*, user, notification_type: str) -> bool:
    """Whether this user wants this type by email.

    Absence of a preference row means defaults, and the default is off — a user
    who has never opened the settings has not consented to email.
    """
    pref = preference_for(user)
    if pref is None or not pref.email_enabled:
        return False
    if notification_type in (pref.muted_types or []):
        # Muting a type mutes it everywhere. A type you do not want to see
        # in-app is certainly not one you want in your inbox.
        return False
    chosen = pref.email_types or []
    return notification_type in chosen if chosen else notification_type in EMAIL_WORTHY


def _from_address() -> str:
    return getattr(settings, "DEFAULT_FROM_EMAIL", "notifications@ledgerflow.app")


def send_notification_email(*, notification: Notification) -> bool:
    """Email one notification. Returns whether it was sent.

    Never raises: a mail provider being slow or down must not fail the
    operation that raised the alert. The failure is logged and the notification
    survives in the in-app inbox regardless, which is the durable channel.
    """
    from apps.common.frontend_urls import build

    user = notification.user
    if user is None or not user.email:
        return False
    if "email" in (notification.delivered_channels or []):
        return False
    if not wants_email(user=user, notification_type=notification.type):
        return False

    severity_prefix = "Action needed: " if notification.severity == "critical" else ""
    body = notification.body or ""
    link = build("notifications")

    text = (
        f"{notification.title}\n\n"
        f"{body}\n\n"
        f"See it in LedgerFlow: {link}\n\n"
        "You're receiving this because email alerts are on for your account. "
        f"Change what you get here: {build('settings/preferences')}\n"
    )

    try:
        message = EmailMultiAlternatives(
            subject=f"{severity_prefix}{notification.title}",
            body=text,
            from_email=_from_address(),
            to=[user.email],
        )
        message.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001 — delivery must not break the caller
        logger.warning("notification %s email failed: %s", notification.id, exc)
        return False

    Notification.objects.filter(pk=notification.pk).update(
        delivered_channels=[*(notification.delivered_channels or []), "email"],
        updated_at=timezone.now(),
    )
    return True


def dispatch_email(notification: Notification) -> None:
    """Queue delivery for after the surrounding transaction commits.

    Two things the task cannot work out for itself, so both travel with it:

    * **`on_commit`** — dispatching inline lets the worker read a notification
      that is not yet visible, the same race that silently swallowed invitation
      emails.
    * **`tenant_id`** — `Notification` and `NotificationPreference` are both
      tenant-scoped, so a worker with no bound tenant cannot even fetch the row
      it was asked to send. Passing the id would be a chicken-and-egg: you need
      the tenant to read the row that tells you the tenant.
    """
    from .tasks import send_notification_email_task

    notification_id = str(notification.id)
    tenant_id = str(notification.tenant_id)
    transaction.on_commit(
        lambda: send_notification_email_task.delay(
            notification_id=notification_id, tenant_id=tenant_id
        )
    )
