"""Notification read side — inbox listing and unread counts."""

from __future__ import annotations

from django.db.models import Q

from .models import Notification


def inbox(*, user, unread_only: bool = False):
    """A user's notifications plus workspace-wide ones (user is null), newest
    first. UNSLICED — the API paginates. Uses the inbox partial indexes."""
    qs = Notification.objects.filter(Q(user=user) | Q(user__isnull=True))
    if unread_only:
        qs = qs.filter(read_at__isnull=True)
    return qs.order_by("-created_at", "-id")


def unread_count(*, user) -> int:
    return (
        Notification.objects.filter(Q(user=user) | Q(user__isnull=True)).filter(read_at__isnull=True).count()
    )
