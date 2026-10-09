"""Transactional email for the users app.

Password-reset delivery lives here, async for the same reason invitation email
is (`apps.tenancy.tasks`): a slow or flaky mail provider must never block — or
fail — the API request that asked for the link. The request endpoint always
returns 200 (no account enumeration); whether an email actually goes out is
decided here, off the request path.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.mail import send_mail

from apps.common.frontend_urls import email_verify as email_verify_url
from apps.common.frontend_urls import password_reset as password_reset_url

logger = logging.getLogger("ledgerflow.users.tasks")


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_password_reset_email(self, *, user_id: str, raw_token: str) -> None:
    """Email a single-use reset link to the account holder.

    `User` is global (not tenant-scoped), so unlike notification email this task
    needs no bound tenant — just the user id and the raw token, which exists
    only in memory and is never stored in the clear.
    """
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        # Legitimate if the account is deleted between request and delivery.
        logger.warning("user %s vanished before its password-reset email was sent", user_id)
        return
    if not user.email:
        return

    reset_url = password_reset_url(raw_token)
    send_mail(
        subject="Reset your LedgerFlow password",
        message=(
            "We received a request to reset the password for your LedgerFlow account.\n\n"
            f"Reset it here: {reset_url}\n\n"
            "This link expires in one hour and can be used only once. "
            "If you did not request a reset you can safely ignore this email — "
            "your password will not change."
        ),
        from_email=None,  # uses DEFAULT_FROM_EMAIL
        recipient_list=[user.email],
        fail_silently=False,
    )


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_email_verification(self, *, user_id: str, raw_token: str) -> None:
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning("user %s vanished before its verification email was sent", user_id)
        return
    if not user.email:
        return
    verify_url = email_verify_url(raw_token)
    send_mail(
        subject="Verify your LedgerFlow email",
        message=(
            "Please confirm this is your email address so we can protect your account.\n\n"
            f"Verify: {verify_url}\n\n"
            "This link expires in 24 hours. If you did not create a LedgerFlow account, "
            "you can ignore this email."
        ),
        from_email=None,
        recipient_list=[user.email],
        fail_silently=False,
    )
