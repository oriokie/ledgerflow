"""URLs into the customer SPA, for links the backend sends by email.

Centralised so a route rename breaks one module rather than silently producing
dead links in transactional email — which is exactly what happened before this
existed. Each helper mirrors a route declared in `frontend/app/src/App.tsx`;
`tests/test_frontend_links.py` asserts they stay in step.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.conf import settings


def _base() -> str:
    return str(getattr(settings, "FRONTEND_BASE_URL", "http://localhost:5173")).rstrip("/")


def build(path: str, **params) -> str:
    """Absolute SPA URL. `path` is the React route, leading slash optional."""
    url = f"{_base()}/{path.lstrip('/')}"
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    return f"{url}?{query}" if query else url


def invitation_accept(token: str) -> str:
    """Route: /invite — see AcceptInvitePage."""
    return build("invite", token=token)


def password_reset(token: str) -> str:
    """Route: /reset-password — see ResetPasswordPage."""
    return build("reset-password", token=token)
