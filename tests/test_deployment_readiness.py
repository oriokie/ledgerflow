"""Deployment probes and production configuration.

The health check used to be `JsonResponse({"status": "ok"})` — a function that
could not fail. It reported healthy with the database down, which is worse than
no probe: an orchestrator keeps routing traffic to an instance that can serve
nothing and never restarts it.

These tests assert the probes can actually fail, which is the only property that
makes a health check worth having.
"""

from __future__ import annotations

import pathlib
import re
from unittest import mock

import pytest

pytestmark = pytest.mark.django_db


# ================================================================= liveness
def test_liveness_answers_without_touching_a_dependency(client):
    """Liveness must not depend on the database.

    If it did, a database outage would fail liveness on every replica at once
    and the orchestrator would restart the entire fleet — turning a recoverable
    dependency blip into a thundering-herd restart loop.
    """
    with mock.patch("django.db.connection.cursor", side_effect=RuntimeError("db is down")):
        response = client.get("/healthz/")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_the_original_probe_path_still_works(client):
    """Existing load-balancer configs and uptime monitors point at /healthz."""
    assert client.get("/healthz/").status_code == 200


# ================================================================ readiness
def test_readiness_reports_ready_when_everything_is_up(client):
    body = client.get("/readyz/").json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": True, "cache": True, "migrations": True}


def test_readiness_fails_when_the_database_is_unreachable(client):
    """The whole point: a probe that cannot fail is not a probe."""
    with mock.patch("apps.common.health_views.connection.cursor", side_effect=RuntimeError("db is down")):
        response = client.get("/readyz/")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] is False


def test_readiness_fails_when_the_cache_is_unreachable(client):
    with mock.patch("apps.common.health_views.cache.set", side_effect=RuntimeError("no redis")):
        response = client.get("/readyz/")
    assert response.status_code == 503
    assert response.json()["checks"]["cache"] is False


def test_readiness_fails_when_the_cache_silently_drops_writes(client):
    """A cache that accepts writes and returns nothing looks healthy to a
    connection test while halving throughput."""
    with mock.patch("apps.common.health_views.cache.get", return_value=None):
        response = client.get("/readyz/")
    assert response.status_code == 503
    assert response.json()["checks"]["cache"] is False


def test_readiness_fails_when_migrations_are_outstanding(client):
    """Holds a new container out of the load balancer until its schema is
    applied — otherwise it serves 500s on exactly the tables that changed and
    nothing else in the stack notices."""
    with mock.patch("apps.common.health_views._migrations_applied", return_value=False):
        response = client.get("/readyz/")
    assert response.status_code == 503
    assert response.json()["checks"]["migrations"] is False


def test_readiness_names_the_failing_dependency(client):
    """An operator reading the probe output should learn which thing is down,
    not merely that something is."""
    with mock.patch("apps.common.health_views.connection.cursor", side_effect=RuntimeError("db is down")):
        checks = client.get("/readyz/").json()["checks"]
    assert checks["database"] is False
    assert checks["cache"] is True


def test_the_probes_leak_nothing_useful_to_an_attacker(client):
    """Neither endpoint is authenticated — an orchestrator has no credentials —
    so neither may expose versions, hostnames or connection strings."""
    for path in ("/healthz/", "/readyz/"):
        body = client.get(path).content.decode().lower()
        for leak in ("postgres://", "redis://", "password", "secret", "traceback", "django/"):
            assert leak not in body, (path, leak)


def test_the_probes_need_no_authentication(client):
    """A probe behind auth is a probe that always fails."""
    assert client.get("/healthz/").status_code == 200
    assert client.get("/readyz/").status_code in (200, 503)


# ============================================== production configuration
PRODUCTION_SETTINGS = pathlib.Path("config/settings/production.py").read_text()

# These assert on the settings *source* rather than importing the module.
# `production.py` raises at import when DJANGO_ALLOWED_HOSTS is absent — which
# is itself the behaviour under test below — and reloading a Django settings
# module mid-suite fights the framework's import caching for no benefit. The
# properties here are all literal declarations, so reading them is exact.


def test_production_refuses_to_boot_without_allowed_hosts():
    """A wildcard host in production is a Host-header attack waiting to happen,
    so the setting is required rather than defaulted — and the failure is at
    import, before the process serves a single request."""
    assert 'raise RuntimeError("DJANGO_ALLOWED_HOSTS must be set in production.")' in (PRODUCTION_SETTINGS)
    assert "if not ALLOWED_HOSTS:" in PRODUCTION_SETTINGS


def test_production_disables_debug_unconditionally():
    """Not `env.bool(...)` with a default — DEBUG in production leaks tracebacks
    containing query parameters and settings, so it must not be switchable."""
    assert re.search(r"^DEBUG = False$", PRODUCTION_SETTINGS, re.M)


def test_production_forces_structured_logs():
    """Console-formatted logs are unparseable by every aggregator."""
    assert 'LOGGING["handlers"]["console"]["formatter"] = "json"' in PRODUCTION_SETTINGS


def test_production_pins_the_transport_security_headers():
    for setting in (
        "SECURE_SSL_REDIRECT",
        "SESSION_COOKIE_SECURE",
        "CSRF_COOKIE_SECURE",
        "SECURE_HSTS_SECONDS",
        "SECURE_HSTS_PRELOAD",
        "SECURE_PROXY_SSL_HEADER",
    ):
        assert setting in PRODUCTION_SETTINGS, setting


def test_production_requires_object_storage():
    """Local-disk media on a container filesystem is lost on every deploy."""
    assert 'STORAGES["default"]["BACKEND"]' in PRODUCTION_SETTINGS
    assert "S3Storage" in PRODUCTION_SETTINGS


def test_error_monitoring_is_opt_in_and_inert_when_unset():
    """Wiring must not break a deployment that does not use it."""
    assert "SENTRY_DSN" in PRODUCTION_SETTINGS
    assert "if SENTRY_DSN:" in PRODUCTION_SETTINGS
    # Household financial data must not accumulate in a third-party tracker.
    assert "send_default_pii=False" in PRODUCTION_SETTINGS


def test_the_container_healthcheck_uses_readiness_not_liveness():
    """Liveness would restart the fleet on a dependency outage; readiness only
    removes the instance from rotation."""
    import pathlib

    compose = pathlib.Path("deploy/docker-compose.server.yml").read_text()
    assert "/readyz/" in compose, "the web service has no healthcheck"
    assert "start_period" in compose, "no grace period for migrations on boot"


def test_every_service_in_the_deployment_has_a_healthcheck():
    import pathlib
    import re

    compose = pathlib.Path("deploy/docker-compose.server.yml").read_text()
    # db, redis and web must all be probed; caddy is a proxy with its own.
    assert len(re.findall(r"healthcheck:", compose)) >= 3
