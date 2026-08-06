"""The admin panel's view of whether anything is watching this deployment.

Worth its own tests because the state it reports is invisible by construction:
a deployment with no monitoring looks exactly like one that has simply had no
incidents. On 2026-08-06 this application was down for six hours and the first
thing that noticed was somebody trying to log in.

The second property here is restraint. "No alerting configured" is a gap to
close, not a live incident, and reporting it as a degradation would leave the
rollup permanently amber on every fresh install — which teaches operators to
ignore the one colour that should mean something.
"""

from __future__ import annotations

import pytest

from apps.platform_admin.health import OK, UNKNOWN, monitoring, overall, snapshot


def _env(monkeypatch, **values):
    for name in (
        "ALERT_WEBHOOK_URL",
        "ALERT_EMAIL_TO",
        "ALERT_SMTP_URL",
        "MONITOR_HEARTBEAT_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


class TestChannels:
    def test_both_layers_configured_is_ok(self, monkeypatch):
        _env(
            monkeypatch,
            ALERT_WEBHOOK_URL="https://hooks.example/x",
            MONITOR_HEARTBEAT_URL="https://hc.example/ping",
        )
        result = monitoring()
        assert result["status"] == OK
        assert result["channels"] == {"webhook": True, "email": False, "heartbeat": True}

    def test_alerting_without_a_heartbeat_names_the_gap(self, monkeypatch):
        """The gap that matters: an on-host monitor dies with its host."""
        _env(monkeypatch, ALERT_WEBHOOK_URL="https://hooks.example/x")
        result = monitoring()
        assert result["status"] == UNKNOWN
        assert "dead host" in result["detail"]

    def test_a_heartbeat_without_alerting_names_the_other_gap(self, monkeypatch):
        _env(monkeypatch, MONITOR_HEARTBEAT_URL="https://hc.example/ping")
        result = monitoring()
        assert "without learning what" in result["detail"]

    def test_nothing_configured_says_so_plainly(self, monkeypatch):
        _env(monkeypatch)
        result = monitoring()
        assert result["status"] == UNKNOWN
        assert "Nothing is watching" in result["detail"]

    def test_email_needs_both_a_recipient_and_a_relay(self, monkeypatch):
        """A recipient with no relay cannot deliver, so it is not a channel."""
        _env(monkeypatch, ALERT_EMAIL_TO="ops@example.com")
        assert monitoring()["channels"]["email"] is False

        _env(
            monkeypatch,
            ALERT_EMAIL_TO="ops@example.com",
            ALERT_SMTP_URL="smtps://smtp.example.com:465",
        )
        assert monitoring()["channels"]["email"] is True

    def test_whitespace_is_not_configuration(self, monkeypatch):
        _env(monkeypatch, ALERT_WEBHOOK_URL="   ")
        assert monitoring()["channels"]["webhook"] is False


class TestRollup:
    def test_missing_monitoring_never_degrades_the_platform(self, monkeypatch):
        """A gap to close is not an incident. Amber on every fresh install
        would train people to ignore the colour."""
        _env(monkeypatch)
        assert overall([{"status": OK}, monitoring()]) == OK

    @pytest.mark.django_db
    def test_it_appears_in_the_snapshot(self, monkeypatch):
        _env(monkeypatch, ALERT_WEBHOOK_URL="https://hooks.example/x")
        names = {c["name"] for c in snapshot()["components"]}
        assert "monitoring" in names
