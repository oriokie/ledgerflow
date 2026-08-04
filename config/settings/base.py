"""Base settings shared by every environment.

Nothing environment-specific lives here (no DEBUG=True, no insecure defaults).
`development.py` / `production.py` / `test.py` import * from this module and
override only what genuinely differs. Every configurable value reads from the
environment via django-environ, with defaults safe enough to fail loudly
rather than silently insecurely.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import environ
from celery.schedules import crontab
from corsheaders.defaults import default_headers as default_cors_headers

BASE_DIR = Path(__file__).resolve().parents[2]

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
)
# .env is optional (Docker/CI inject real env vars); local dev may use one.
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.postgres",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
]

LOCAL_APPS = [
    "apps.common",
    "apps.users",
    "apps.tenancy",
    "apps.ledger",
    "apps.fx",
    "apps.finance",
    "apps.budgeting",
    "apps.intelligence",
    "apps.investments",
    "apps.debt",
    "apps.receipts",
    "apps.analytics",
    "apps.goals",
    "apps.income",
    "apps.notifications",
    "apps.billing",
    "apps.platform_admin",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

AUTH_USER_MODEL = "users.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.common.middleware.RequestIDMiddleware",
    "apps.common.middleware.RequestLoggingMiddleware",
    # NOTE: tenant resolution is NOT Django middleware — see apps/common/api_base.py
    # for why it must happen at the DRF layer (after JWT auth resolves request.user).
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
DATABASES = {
    "default": {
        **env.db("DATABASE_URL", default="postgres://app:app@localhost:5432/ledgerflow"),
        "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=60),
        # Validate a persistent connection before reusing it, so a connection
        # dropped by the server (or a pooler) is transparently reopened instead
        # of surfacing as an error on the next request. Cheap and eliminates a
        # common class of intermittent 500s under CONN_MAX_AGE > 0.
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "connect_timeout": 5,
            # TCP keepalives keep long-lived pooled connections from being
            # silently reaped by a firewall/load balancer.
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        },
        "ATOMIC_REQUESTS": False,  # services manage their own transactions explicitly
    }
}

# --------------------------------------------------------------------------
# Cache / Redis
# --------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        "KEY_PREFIX": "ledgerflow",
    }
}

# --------------------------------------------------------------------------
# Celery
# --------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_ACKS_LATE = True  # redeliver if worker dies mid-task
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # fair dispatch for long-ish financial tasks
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240

CELERY_BEAT_SCHEDULE = {
    "relay-outbox-events": {
        "task": "apps.common.tasks.relay_outbox",
        "schedule": 5.0,  # seconds — near-real-time event delivery
    },
    "run-recurring-transactions": {
        "task": "finance.dispatch_recurring_transactions",
        "schedule": crontab(hour=1, minute=0),  # daily at 01:00 server time
    },
    "reconcile-account-balances": {
        "task": "finance.reconcile_account_balances",
        "schedule": crontab(hour=3, minute=0, day_of_week=0),  # weekly, Sunday 03:00
    },
    "daily-alert-sweep": {
        "task": "notifications.dispatch_alert_sweep",
        "schedule": crontab(hour=7, minute=0),  # daily at 07:00 — bill/budget alerts
    },
    "coach-daily-run": {
        "task": "intelligence.dispatch_coach_run",
        # After the nightly recurring/bill jobs, so the coach reasons over
        # today's posted state rather than yesterday's.
        "schedule": crontab(hour=5, minute=30),
    },
    "notifications-monthly-summary": {
        "task": "notifications.send_monthly_summaries",
        # 08:00 on the 1st. Early enough to be the first thing in the inbox on
        # the day people think about last month, late enough that the previous
        # month's final transactions have settled.
        "schedule": crontab(day_of_month=1, hour=8, minute=0),
    },
    "platform-run-dunning": {
        "task": "platform.run_dunning",
        # Hourly: retries and reminders are scheduled to the day, so hourly
        # resolution is ample, and it keeps a provider outage from delaying a
        # whole day's recovery attempts.
        "schedule": crontab(minute=15),
    },
    "platform-mark-overdue-invoices": {
        "task": "platform.mark_overdue_invoices",
        "schedule": crontab(hour=0, minute=30),
    },
    "platform-expire-impersonations": {
        "task": "platform.expire_impersonations",
        "schedule": 300.0,  # every 5 minutes — an abandoned session is a live credential
    },
    "platform-capture-usage": {
        "task": "platform.capture_usage_snapshots",
        "schedule": crontab(hour=4, minute=0),
    },
    "platform-sweep-alerts": {
        "task": "platform.sweep_alerts",
        "schedule": 900.0,  # every 15 minutes
    },
    "goal-auto-contributions": {
        "task": "goals.dispatch_auto_contributions",
        # Daily, after recurring transactions have posted so a standing transfer
        # into savings is already on the ledger when the goal records it.
        # The service is idempotent per goal per month, so a daily sweep simply
        # catches each goal on or after its chosen day.
        "schedule": crontab(hour=2, minute=0),
    },
}

# --------------------------------------------------------------------------
# Password validation
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Password hashing — Argon2 first (memory-hard, GPU-crack-resistant).
# Django keeps the rest as fallback so already-hashed PBKDF2 passwords from
# before this change still verify; they're transparently re-hashed to Argon2
# on next successful login (Django's default upgrade-in-place behavior).
# --------------------------------------------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# i18n / timezone — global-first product
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"  # storage always UTC; localize at the edge per-user
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static / media (object storage wired per-environment)
# --------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": env("DEFAULT_FILE_STORAGE", default="django.core.files.storage.FileSystemStorage")
    },
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# AWS S3 / object storage (used when DEFAULT_FILE_STORAGE targets it)
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default="")  # supports R2/MinIO/etc.
AWS_DEFAULT_ACL = None
AWS_S3_FILE_OVERWRITE = False

# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="LedgerFlow <no-reply@ledgerflow.app>")

# --------------------------------------------------------------------------
# Attachments (receipts/documents via presigned upload)
# --------------------------------------------------------------------------
ATTACHMENT_UPLOAD_TTL_SECONDS = env.int("ATTACHMENT_UPLOAD_TTL_SECONDS", default=900)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# DRF
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        # SessionAuthentication is deliberately absent. The only client is a
        # JWT-bearer SPA and the renderer set is JSON-only, so there is no
        # browsable API to serve — it authenticated nothing the product needs
        # while widening the surface: a Django session cookie authenticated API
        # *reads* (writes were CSRF-protected, reads were not). Combined with
        # CORS_ALLOW_CREDENTIALS = True, that turned any future CORS origin
        # mistake into cross-origin access to financial data.
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.CursorPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "auth": env("THROTTLE_AUTH", default="10/min"),
        "mfa_verify": env("THROTTLE_MFA_VERIFY", default="5/min"),
        "write": env("THROTTLE_WRITE", default="120/min"),
        "read": env("THROTTLE_READ", default="1000/min"),
    },
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("JWT_ACCESS_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_DAYS", default=14)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,  # handled explicitly (stamps IP too)
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "LedgerFlow API",
    "DESCRIPTION": "Multi-tenant personal finance platform API.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# --------------------------------------------------------------------------
# Field-level encryption (TOTP secrets, OAuth refresh tokens at rest).
# A dedicated key, NOT SECRET_KEY — rotating SECRET_KEY (e.g. to invalidate
# sessions) must never silently corrupt encrypted MFA secrets, and vice versa.
# --------------------------------------------------------------------------
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")

# --------------------------------------------------------------------------
# MFA (TOTP + backup codes)
# --------------------------------------------------------------------------
MFA_ISSUER_NAME = env("MFA_ISSUER_NAME", default="LedgerFlow")
MFA_CHALLENGE_TTL_SECONDS = env.int("MFA_CHALLENGE_TTL_SECONDS", default=300)
MFA_BACKUP_CODE_COUNT = env.int("MFA_BACKUP_CODE_COUNT", default=10)
MFA_TOTP_VALID_WINDOW = env.int("MFA_TOTP_VALID_WINDOW", default=1)  # +/- 30s steps

# --------------------------------------------------------------------------
# WebAuthn / Passkeys
# --------------------------------------------------------------------------
WEBAUTHN_RP_ID = env("WEBAUTHN_RP_ID", default="localhost")
WEBAUTHN_RP_NAME = env("WEBAUTHN_RP_NAME", default="LedgerFlow")
WEBAUTHN_ORIGINS = env.list("WEBAUTHN_ORIGINS", default=["http://localhost:3000"])
WEBAUTHN_CHALLENGE_TTL_SECONDS = env.int("WEBAUTHN_CHALLENGE_TTL_SECONDS", default=300)

# --------------------------------------------------------------------------
# OAuth / social login — config-over-hardcode: providers are entirely
# environment-driven, so adding one is an env change, not a code change.
# Empty client_id/secret => provider is disabled (endpoints 404 gracefully).
# --------------------------------------------------------------------------
OAUTH_PROVIDERS = {
    "google": {
        "client_id": env("OAUTH_GOOGLE_CLIENT_ID", default=""),
        "client_secret": env("OAUTH_GOOGLE_CLIENT_SECRET", default=""),
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
    },
    "apple": {
        "client_id": env("OAUTH_APPLE_CLIENT_ID", default=""),
        "client_secret": env("OAUTH_APPLE_CLIENT_SECRET", default=""),
        "authorize_url": "https://appleid.apple.com/auth/authorize",
        "token_url": "https://appleid.apple.com/auth/token",
        "userinfo_url": "",  # Apple ships identity in the token's id_token claims, not a userinfo endpoint
        "scope": "openid email name",
    },
}
OAUTH_REDIRECT_URI = env("OAUTH_REDIRECT_URI", default="http://localhost:5173/auth/callback")

# Where the customer-facing SPA is served. Every link the backend puts in an
# email must be built from this and nothing else.
#
# It exists because it did not: invitation emails previously derived their URL
# by string-slicing OAUTH_REDIRECT_URI, which produced the wrong origin, a
# stray path segment and a route that was never registered. A setting whose
# only job is "where does the frontend live" removes the temptation to infer it
# from something adjacent.
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="http://localhost:5173").rstrip("/")
OAUTH_STATE_TTL_SECONDS = env.int("OAUTH_STATE_TTL_SECONDS", default=600)

# --------------------------------------------------------------------------
# Invitations
# --------------------------------------------------------------------------
INVITATION_TTL_DAYS = env.int("INVITATION_TTL_DAYS", default=7)

# --------------------------------------------------------------------------
# Platform administration workspace
# --------------------------------------------------------------------------
# How long an impersonation grant stays usable. Short by default: this is a
# licence to read a household's financial records, and the common support case
# is minutes, not hours. Operators can request a longer TTL per session, capped
# by the API serializer.
PLATFORM_IMPERSONATION_TTL_MINUTES = env.int("PLATFORM_IMPERSONATION_TTL_MINUTES", default=30)
# Whether a platform operator account is barred from also owning a customer
# workspace. Default on — see apps/platform_admin/separation.py for the
# reasoning. Turn off knowingly (e.g. a solo founder dogfooding the product).
PLATFORM_STAFF_SEPARATE_FROM_TENANTS = env.bool("PLATFORM_STAFF_SEPARATE_FROM_TENANTS", default=True)
# Queue depth above which the health dashboard reports the workers as degraded.
PLATFORM_QUEUE_BACKLOG_THRESHOLD = env.int("PLATFORM_QUEUE_BACKLOG_THRESHOLD", default=500)

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True
# The SPA sends the tenant on a custom header; it must be allowed through the
# CORS preflight or browsers block every tenant-scoped request. (curl/server
# clients bypass preflight, so this only bites real browser traffic.)
CORS_ALLOW_HEADERS = (*default_cors_headers, "x-tenant-id")

# --------------------------------------------------------------------------
# Security headers (safe defaults; production.py raises the bar further)
# --------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # must be readable by JS for header-based CSRF submission
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# --------------------------------------------------------------------------
# Logging — structured JSON, request-id correlated (see apps/common/logging.py)
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "apps.common.logging.RequestIDFilter"}},
    "formatters": {
        "json": {"()": "apps.common.logging.JSONFormatter"},
        "console": {"format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": env("LOG_FORMATTER", default="console"),
            "filters": ["request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "ledgerflow": {
            "handlers": ["console"],
            "level": env("LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Intelligence / AI & automation
# ---------------------------------------------------------------------------
# Which concrete provider backs each AI capability. Empty dict => deterministic
# defaults (see apps.intelligence.registry). To activate an LLM later, add e.g.
#   "categorization": "apps.intelligence.providers.llm.LLMCategorizer"
# No caller changes required — the registry resolves these by dotted path.
# Outbox event publisher (read side of the transactional outbox). Default
# delivers to the structured log so events are never lost before a broker
# is wired; swap for a broker publisher by dotted path, no relay change.
EVENT_PUBLISHER = env("EVENT_PUBLISHER", default="apps.common.publishing.LoggingPublisher")

INTELLIGENCE_PROVIDERS: dict[str, str] = {}

# Confidence at/above which a category suggestion is auto-applied to an
# uncategorized transaction (below it, the suggestion waits for a human). This
# single dial moves the product between "assistive" and "autonomous".
INTELLIGENCE_AUTO_ACCEPT_CONFIDENCE = 0.9

# --------------------------------------------------------------------------
# Billing / payment providers. All blank by default -> sandbox mode (flows
# work end-to-end without real credentials). Set these to go live.
# --------------------------------------------------------------------------
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")

MPESA_CONSUMER_KEY = env("MPESA_CONSUMER_KEY", default="")
MPESA_CONSUMER_SECRET = env("MPESA_CONSUMER_SECRET", default="")
MPESA_SHORTCODE = env("MPESA_SHORTCODE", default="")
MPESA_PASSKEY = env("MPESA_PASSKEY", default="")
MPESA_API_BASE = env("MPESA_API_BASE", default="https://sandbox.safaricom.co.ke")
MPESA_CALLBACK_URL = env("MPESA_CALLBACK_URL", default="")


# --------------------------------------------------------------------------
# AI / LLM configuration
# --------------------------------------------------------------------------
# The product is fully functional with all of this off — the deterministic
# providers are the shipping implementation, not a placeholder. An LLM is an
# upgrade path, and everything below is optional.
#
# LLM_PROVIDER selects a connection preset (see apps.intelligence.llm):
#   Hosted, free tier available: google, groq, openrouter, together, mistral
#   Hosted, paid:                openai, anthropic, deepseek
#   Local, no key needed:        ollama, lmstudio
#   Anything else:               custom (set LLM_BASE_URL yourself)
#
# Presets only supply defaults; LLM_BASE_URL and LLM_MODEL always win, so an
# unlisted OpenAI-compatible endpoint needs no code change.
LLM_ENABLED = env.bool("LLM_ENABLED", default=False)
LLM_PROVIDER = env("LLM_PROVIDER", default="custom")
LLM_MODEL = env("LLM_MODEL", default="")
LLM_BASE_URL = env("LLM_BASE_URL", default="")
LLM_API_KEY = env("LLM_API_KEY", default="")
LLM_TIMEOUT_SECONDS = env.int("LLM_TIMEOUT_SECONDS", default=20)
LLM_MAX_OUTPUT_TOKENS = env.int("LLM_MAX_OUTPUT_TOKENS", default=1500)

# Sending a household's spending summary to a third party is a decision an
# operator must make deliberately, so it is a separate switch from LLM_ENABLED
# and defaults to off. Local providers (ollama, lmstudio) are exempt: nothing
# leaves the machine.
LLM_SHARE_FINANCIAL_CONTEXT = env.bool("LLM_SHARE_FINANCIAL_CONTEXT", default=False)

# Which implementation backs each intelligence capability. Defaults are the
# deterministic providers; point these at the LLM ones to switch:
#
#   INTELLIGENCE_PROVIDERS = {
#       "insight":   "apps.intelligence.providers.llm_coach.LLMCoach",
#       "narrative": "apps.intelligence.providers.llm_coach.LLMNarrator",
#   }
#
# Narration is the safer half to enable first: rewording figures already
# computed by the engine carries far less risk than deciding what is true.
INTELLIGENCE_PROVIDERS = env.json("INTELLIGENCE_PROVIDERS", default={})


# --------------------------------------------------------------------------
# Web Push (VAPID)
# --------------------------------------------------------------------------
# Push, like the LLM providers, is optional infrastructure — the product works
# fully with it unset. `vapid_configured()` in apps.notifications.push is the
# single place that decides whether a send is attempted; nothing else needs to
# know these are empty.
#
# Generate a real keypair once per deployment with:
#   python3 -c "from py_vapid import Vapid; v = Vapid(); v.generate_keys(); \
#     print(v.private_key.private_numbers().private_value)"
# or the vapid CLI shipped by py-vapid. Never share the private key between
# environments — a leaked one lets anyone impersonate this server to browsers
# that have already subscribed.
VAPID_PRIVATE_KEY = env("VAPID_PRIVATE_KEY", default="")
VAPID_PUBLIC_KEY = env("VAPID_PUBLIC_KEY", default="")
VAPID_CLAIMS_EMAIL = env("VAPID_CLAIMS_EMAIL", default="")


# --------------------------------------------------------------------------
# Receipt OCR
# --------------------------------------------------------------------------
# "tesseract" (default) reads locally, no network call, no per-image cost.
# "null" disables OCR entirely — receipts still upload and can be filled in by
# hand. A cloud vendor is a third value once a provider class exists for it;
# see apps.receipts.providers.
RECEIPTS_OCR_PROVIDER = env("RECEIPTS_OCR_PROVIDER", default="tesseract")
