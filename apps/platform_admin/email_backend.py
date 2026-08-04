"""An SMTP backend configured from the platform settings store.

Django resolves `EMAIL_HOST` and friends from `settings` at import time, so
mail configuration was reachable only through the environment: an operator whose
relay credentials were wrong had to edit `.env` and redeploy to fix it. That is
the wrong shape for the one setting whose failure mode is silent — nobody
notices a broken relay until an invitation or a password reset does not arrive,
and by then the person waiting for it has already given up.

This resolves each connection's settings when the connection is opened, so a
change made in the console takes effect on the next message rather than the next
deploy. Anything not stored falls through to the environment exactly as before,
which is what makes adopting this a no-op for a deployment that is happy with
its `.env`.
"""

from __future__ import annotations

import logging

from django.conf import settings as django_settings
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend

logger = logging.getLogger("ledgerflow.email")

#: Store key → the keyword argument Django's SMTP backend expects.
_CONNECTION_KEYS = {
    "email.host": "host",
    "email.port": "port",
    "email.username": "username",
    "email.password": "password",
    "email.use_tls": "use_tls",
}


def _stored(key: str):
    """One setting, or None when the store cannot answer.

    Deliberately forgiving: this runs during password resets and invitations,
    and a migration that has not run yet, or a database blip, must degrade to
    the environment's configuration rather than take outbound mail down
    entirely.
    """
    try:
        from .settings_store import get

        return get(key)
    except Exception:  # noqa: BLE001 - see docstring
        logger.warning("Could not read %s from the settings store; using the environment.", key)
        return None


def resolve_from_email() -> str:
    """The configured sender, falling back to DEFAULT_FROM_EMAIL."""
    stored = _stored("email.from_address")
    if stored:
        return str(stored)
    return django_settings.DEFAULT_FROM_EMAIL


class PlatformConfiguredEmailBackend(SMTPEmailBackend):
    """SMTP, with host/port/credentials taken from the settings store."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key, attribute in _CONNECTION_KEYS.items():
            value = _stored(key)
            # An empty string means "not configured here", not "set to empty":
            # blanking a field in the console must fall back to the
            # environment, not silently point the relay at nowhere. `use_tls`
            # is exempt because False is a meaningful stored value.
            if value in (None, "") and attribute != "use_tls":
                continue
            if attribute == "use_tls":
                if value is None:
                    continue
                setattr(self, attribute, bool(value))
                continue
            setattr(self, attribute, value)

        # Django refuses a connection with both on, and the pairing is implied
        # by the port anyway — 465 is implicit TLS, 587 is STARTTLS.
        if self.use_tls and self.use_ssl:
            self.use_ssl = False

    def send_messages(self, email_messages):
        """Stamp the configured sender on messages that did not choose one.

        A message whose `from_email` is the project default is one where no
        caller expressed a preference, so the operator's choice applies. One
        that names its own sender deliberately keeps it — invoices addressed
        from a billing alias must not be rewritten.
        """
        configured = resolve_from_email()
        if configured and configured != django_settings.DEFAULT_FROM_EMAIL:
            for message in email_messages:
                if not message.from_email or message.from_email == django_settings.DEFAULT_FROM_EMAIL:
                    message.from_email = configured
        return super().send_messages(email_messages)
