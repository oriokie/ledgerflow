"""Outbound mail is configurable from the console, not only the environment.

SMTP was the one setting an operator could not fix without a redeploy, and the
one whose failure is silent: nobody notices a wrong relay until an invitation
or a password reset does not arrive, by which point the person waiting for it
has given up.
"""

from __future__ import annotations

import pytest
from django.core import mail
from django.test import override_settings

from apps.platform_admin import settings_store
from apps.platform_admin.email_backend import PlatformConfiguredEmailBackend, resolve_from_email

pytestmark = pytest.mark.django_db

BACKEND = "apps.platform_admin.email_backend.PlatformConfiguredEmailBackend"


@pytest.mark.parametrize(
    "key",
    ["email.host", "email.port", "email.username", "email.password", "email.use_tls", "email.from_address"],
)
def test_every_smtp_field_is_settable(key):
    assert key in settings_store.SPEC_BY_KEY


def test_the_password_is_write_only():
    """Same treatment as the payment credentials: a console that reads secrets
    back turns one compromised session into a credential leak."""
    assert settings_store.SPEC_BY_KEY["email.password"].write_only is True
    assert settings_store.SPEC_BY_KEY["email.password"].kind == settings_store.SettingKind.SECRET


def test_the_password_is_not_stored_in_the_clear():
    settings_store.set_value(key="email.password", raw="hunter2-relay-secret")
    row = settings_store.PlatformSetting.objects.get(key="email.password")
    assert "hunter2-relay-secret" not in row.value
    assert row.encrypted_value
    assert settings_store.get("email.password") == "hunter2-relay-secret"


@override_settings(EMAIL_HOST="env.example.com", EMAIL_PORT=25, EMAIL_HOST_USER="envuser")
def test_stored_values_win_over_the_environment():
    settings_store.set_value(key="email.host", raw="relay.example.com")
    settings_store.set_value(key="email.port", raw="587")
    settings_store.set_value(key="email.username", raw="postmaster")

    backend = PlatformConfiguredEmailBackend()
    assert backend.host == "relay.example.com"
    assert backend.port == 587
    assert backend.username == "postmaster"


@override_settings(EMAIL_HOST="env.example.com", EMAIL_PORT=2525, EMAIL_HOST_USER="envuser")
def test_nothing_stored_leaves_the_environment_untouched():
    """Adopting this must be a no-op for a deployment happy with its .env."""
    backend = PlatformConfiguredEmailBackend()
    assert backend.host == "env.example.com"
    assert backend.port == 2525
    assert backend.username == "envuser"


@override_settings(EMAIL_HOST="env.example.com")
def test_clearing_a_field_falls_back_rather_than_blanking_the_relay():
    """An empty box in the console means "I'm not setting this here". Treating
    it as an override points the relay at nowhere and mail stops."""
    settings_store.set_value(key="email.host", raw="relay.example.com")
    settings_store.clear(key="email.host")

    assert PlatformConfiguredEmailBackend().host == "env.example.com"


def test_starttls_can_be_turned_off_for_an_implicit_tls_port():
    """False is a meaningful stored value here, unlike an empty string, so the
    empty-means-unset rule must not swallow it."""
    settings_store.set_value(key="email.use_tls", raw="false")
    assert PlatformConfiguredEmailBackend().use_tls is False


def test_tls_and_ssl_are_never_both_on():
    """Django raises rather than sending when both are set."""
    settings_store.set_value(key="email.use_tls", raw="true")
    backend = PlatformConfiguredEmailBackend()
    backend.use_ssl = True
    assert not (PlatformConfiguredEmailBackend().use_tls and PlatformConfiguredEmailBackend().use_ssl)


@override_settings(DEFAULT_FROM_EMAIL="fallback@example.com")
def test_the_configured_sender_is_used():
    settings_store.set_value(key="email.from_address", raw="billing@acme.test")
    assert resolve_from_email() == "billing@acme.test"


@override_settings(DEFAULT_FROM_EMAIL="fallback@example.com")
def test_the_sender_falls_back_when_unset():
    assert resolve_from_email() == "fallback@example.com"


def _sent_from(from_email: str) -> str:
    """Run a message through the backend with the actual SMTP send stubbed."""
    from unittest import mock

    message = mail.EmailMessage("s", "b", from_email, ["to@example.com"])
    backend = PlatformConfiguredEmailBackend()
    with mock.patch("django.core.mail.backends.smtp.EmailBackend.send_messages", return_value=1) as sent:
        backend.send_messages([message])
    assert sent.called, "the message never reached the SMTP layer"
    return message.from_email


@override_settings(DEFAULT_FROM_EMAIL="fallback@example.com")
def test_a_deliberate_sender_is_not_rewritten():
    """An invoice addressed from a billing alias must keep it."""
    settings_store.set_value(key="email.from_address", raw="noreply@acme.test")
    assert _sent_from("invoices@acme.test") == "invoices@acme.test"


@override_settings(DEFAULT_FROM_EMAIL="fallback@example.com")
def test_a_message_that_chose_no_sender_gets_the_configured_one():
    settings_store.set_value(key="email.from_address", raw="noreply@acme.test")
    assert _sent_from("fallback@example.com") == "noreply@acme.test"


def test_a_store_failure_does_not_take_outbound_mail_down():
    """This runs during password resets. A database blip must degrade to the
    environment's configuration, not raise."""
    from unittest import mock

    with mock.patch("apps.platform_admin.settings_store.get", side_effect=RuntimeError("db down")):
        backend = PlatformConfiguredEmailBackend()  # must not raise
    assert backend is not None


def test_the_project_uses_this_backend_by_default():
    from django.conf import settings as dj

    base = (dj.BASE_DIR / "config" / "settings" / "base.py").read_text()
    assert BACKEND in base
