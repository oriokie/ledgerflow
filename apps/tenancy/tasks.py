"""Invitation email delivery — asynchronous so a slow mail provider never
blocks the API request that created the invitation."""

from __future__ import annotations

import logging

from celery import shared_task
from django.core.mail import send_mail

from apps.common.frontend_urls import invitation_accept

logger = logging.getLogger("ledgerflow.tenancy.tasks")


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_invitation_email(self, *, invitation_id: str, raw_token: str) -> None:
    from .models import Invitation

    try:
        invitation = Invitation.objects.select_related("tenant", "invited_by").get(id=invitation_id)
    except Invitation.DoesNotExist:
        # Legitimate when an invitation is revoked between creation and
        # delivery. Logged rather than swallowed: this branch also used to
        # absorb the dispatch-before-commit race, and a silent return meant
        # nobody could tell the difference for as long as that bug existed.
        logger.warning("invitation %s vanished before its email was sent", invitation_id)
        return

    accept_url = invitation_accept(raw_token)
    inviter_name = invitation.invited_by.full_name if invitation.invited_by else "Someone"

    send_mail(
        subject=f"{inviter_name} invited you to join {invitation.tenant.name} on LedgerFlow",
        message=(
            f"{inviter_name} invited you to join the '{invitation.tenant.name}' workspace "
            f"as a {invitation.get_role_display()}.\n\nAccept: {accept_url}\n\n"
            f"This invitation expires on {invitation.expires_at:%Y-%m-%d}."
        ),
        from_email=None,  # uses DEFAULT_FROM_EMAIL
        recipient_list=[invitation.email],
        fail_silently=False,
    )
