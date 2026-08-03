"""Records `LoginEvent` rows. Kept separate from `auth.py` so the
orchestration logic doesn't need to know about request metadata extraction —
views call this explicitly once the outcome (success/failure/reason) is known."""

from __future__ import annotations

from ..security_events import LoginEvent


def _client_ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")


def record_login_event(
    *, request, email: str, method: str, success: bool, user=None, reason: str = ""
) -> None:
    LoginEvent.objects.create(
        user=user,
        email_attempted=email.strip().lower(),
        method=method,
        success=success,
        reason=reason,
        ip_address=_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:255] if request else ""),
    )
