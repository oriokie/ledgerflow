"""Production. Every relaxed default from base.py is tightened here."""

from .base import *  # noqa: F401,F403

DEBUG = False

if not ALLOWED_HOSTS:  # noqa: F405
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be set in production.")
# Docker's own readiness healthcheck (docker-compose.server.yml) curls
# localhost:8000 from inside the container. That port is only `expose`d, never
# published to the host, so it's unreachable from outside the container
# network — safe to whitelist unconditionally rather than making every
# deployment add it to DJANGO_ALLOWED_HOSTS themselves.
ALLOWED_HOSTS = [*ALLOWED_HOSTS, "localhost"]  # noqa: F405
# Secret-key *strength* (length, entropy) is validated by `manage.py check --deploy`,
# which CI/CD should run before every production release.

SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)  # noqa: F405
# Health probes are plain HTTP by design: the container healthcheck, and any
# load balancer or orchestrator probe, talk to the port directly rather than
# through the TLS terminator. Redirecting them to https means the probe reads
# a 301 instead of a 200 and calls a perfectly healthy container dead — which
# is exactly what happened once the Host header started validating.
SECURE_REDIRECT_EXEMPT = [r"^healthz/?$", r"^readyz/?$"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("DJANGO_HSTS_SECONDS", default=60 * 60 * 24 * 365)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Some reverse proxies (e.g. a shared-hosting vhost that can't set
# ProxyPreserveHost) can't rewrite the Host header, only add
# X-Forwarded-Host. Without this, ALLOWED_HOSTS validates against the
# proxy's own backend address instead of the public hostname and every
# request gets rejected as DisallowedHost.
USE_X_FORWARDED_HOST = True

# Object storage becomes mandatory in production (no local filesystem media).
STORAGES["default"]["BACKEND"] = env(  # noqa: F405
    "DEFAULT_FILE_STORAGE", default="storages.backends.s3.S3Storage"
)

LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405


# --------------------------------------------------------------------------
# Error monitoring
# --------------------------------------------------------------------------
# Opt-in: wiring activates only when SENTRY_DSN is set, so nothing changes for
# a deployment that does not want it and nothing breaks if the package is
# absent. Until something is configured here, the only record of a production
# exception is a line in stdout that nobody is paged about.
#
# `send_default_pii` is off deliberately. This product handles household
# financial data, and an error tracker that captures request bodies would
# accumulate transaction memos, payee names and amounts in a third-party
# system that was never part of the privacy posture.
SENTRY_DSN = env("SENTRY_DSN", default="")  # noqa: F405
if SENTRY_DSN:  # pragma: no cover - exercised only in a configured deployment
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.django import DjangoIntegration

        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[DjangoIntegration(), CeleryIntegration()],
            environment=env("SENTRY_ENVIRONMENT", default="production"),  # noqa: F405
            release=env("APP_RELEASE", default=""),  # noqa: F405
            # Sampled, not exhaustive: full tracing on a finance API is a large
            # bill for data nobody reads.
            traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.05),  # noqa: F405
            send_default_pii=False,
        )
    except ImportError:  # pragma: no cover
        import logging

        logging.getLogger("ledgerflow").warning(
            "SENTRY_DSN is set but sentry-sdk is not installed; errors will not be reported."
        )
