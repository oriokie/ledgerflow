# Configuration

All configuration is environment-driven (`django-environ`), read once in
`config/settings/base.py` with safe, fail-loud defaults. `development.py`,
`production.py`, and `test.py` each `from .base import *` and override only
what genuinely differs per environment — see the bottom of this doc.

Locally, values come from a `.env` file (copy `.env.example`); in Docker/CI
they're injected as real environment variables. `.env` is optional — if
absent, `env()` calls fall back to their defaults or raise if no default is
given (e.g. `DJANGO_SECRET_KEY` has no default; the app refuses to start
without one).

## Core Django

| Variable | Default | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | *(required, no default)* | Django's cryptographic signing key. Generate with `django.core.management.utils.get_random_secret_key()`. |
| `DJANGO_DEBUG` | `False` | Never `True` in production; `development.py` forces it `True` regardless. |
| `DJANGO_ALLOWED_HOSTS` | `[]` | Comma-separated. `production.py` raises `RuntimeError` at import time if empty. |
| `LOG_LEVEL` | `INFO` | Applies to the `django`, `celery`, and `ledgerflow.*` loggers. |
| `LOG_FORMATTER` | `console` | `console` (human-readable) or `json` (structured; `production.py` forces `json`). |

## Database

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgres://app:app@localhost:5432/ledgerflow` | Standard `postgres://user:pass@host:port/db` URL. |
| `DB_CONN_MAX_AGE` | `60` (seconds) | Persistent connections. `test.py` forces `0` to avoid connection-state bleed between tests. `CONN_HEALTH_CHECKS=True` and TCP keepalives are always on (not configurable) — see `ARCHITECTURE.md` performance notes. |

RLS and the append-only triggers are PostgreSQL-only DDL
(`apps/ledger/migrations/0002_financial_integrity.py`); they no-op on any
other backend, which is what lets `test.py` optionally fall back to SQLite in
constrained CI, though PostgreSQL is what CI and production actually run
against.

## Redis / Cache / Celery

| Variable | Default | Notes |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Backs the default cache AND is the default broker/result-backend if the Celery-specific vars are unset. |
| `CELERY_BROKER_URL` | `REDIS_URL` | |
| `CELERY_RESULT_BACKEND` | `REDIS_URL` | |
| `EVENT_PUBLISHER` | `apps.common.publishing.LoggingPublisher` | Dotted path to the outbox event publisher. See `apps.common.publishing.RedisStreamPublisher` for a broker example. |

`test.py` always forces `CELERY_TASK_ALWAYS_EAGER=True` (tasks run
synchronously in-process, no broker needed) and `LocMemCache`, regardless of
`REDIS_URL`.

## Object storage (attachments, static files)

| Variable | Default | Notes |
|---|---|---|
| `DEFAULT_FILE_STORAGE` | `django.core.files.storage.FileSystemStorage` | `production.py` defaults this to `storages.backends.s3.S3Storage` instead. |
| `AWS_STORAGE_BUCKET_NAME` | `""` | |
| `AWS_S3_REGION_NAME` | `""` | |
| `AWS_S3_ENDPOINT_URL` | `""` | Set to use an S3-compatible provider (Cloudflare R2, MinIO) instead of AWS. |
| `ATTACHMENT_UPLOAD_TTL_SECONDS` | `900` | Presigned upload URL expiry — see `apps.finance.attachments`. |

## Email

| Variable | Default | Notes |
|---|---|---|
| `EMAIL_BACKEND` | `django.core.mail.backends.smtp.EmailBackend` | `development.py` forces the console backend; `test.py` forces the in-memory backend. |
| `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `EMAIL_USE_TLS` | standard SMTP | |
| `DEFAULT_FROM_EMAIL` | `LedgerFlow <no-reply@ledgerflow.app>` | |

## Auth, MFA, WebAuthn, OAuth

| Variable | Default | Notes |
|---|---|---|
| `JWT_ACCESS_MINUTES` | `15` | |
| `JWT_REFRESH_DAYS` | `14` | Rotates on use, blacklisted after rotation. |
| `FIELD_ENCRYPTION_KEY` | `""` | **Required for MFA to work.** Fernet key encrypting TOTP secrets at rest — deliberately separate from `DJANGO_SECRET_KEY` (rotating one must never corrupt the other's data). Generate with `Fernet.generate_key()`. Production should source this from a real secrets manager, not plain env — see `apps/common/crypto.py`. |
| `MFA_ISSUER_NAME` | `LedgerFlow` | Shown in the authenticator app. |
| `MFA_CHALLENGE_TTL_SECONDS` | `300` | How long a post-password, pre-MFA challenge token is valid. |
| `MFA_BACKUP_CODE_COUNT` | `10` | |
| `MFA_TOTP_VALID_WINDOW` | `1` | ± steps (30s each) of clock drift tolerated. |
| `WEBAUTHN_RP_ID` | `localhost` | Relying Party ID — must match the frontend's domain in production. |
| `WEBAUTHN_RP_NAME` | `LedgerFlow` | |
| `WEBAUTHN_ORIGINS` | `["http://localhost:3000"]` | Comma-separated list of allowed origins for passkey ceremonies. |
| `WEBAUTHN_CHALLENGE_TTL_SECONDS` | `300` | |
| `OAUTH_GOOGLE_CLIENT_ID` / `OAUTH_GOOGLE_CLIENT_SECRET` | `""` | Empty = provider disabled (its endpoints exist but fail gracefully). |
| `OAUTH_APPLE_CLIENT_ID` / `OAUTH_APPLE_CLIENT_SECRET` | `""` | Same. |
| `OAUTH_REDIRECT_URI` | `http://localhost:3000/auth/callback` | |
| `OAUTH_STATE_TTL_SECONDS` | `600` | |

Adding a third OAuth provider is a config change, not a code change — see
`OAUTH_PROVIDERS` in `config/settings/base.py` and
[`EXTENSION_POINTS.md`](./EXTENSION_POINTS.md).

## Throttling

| Variable | Default | Applies to |
|---|---|---|
| `THROTTLE_AUTH` | `10/min` | Login, register, refresh |
| `THROTTLE_MFA_VERIFY` | `5/min` | MFA code verification (the brute-force target) |
| `THROTTLE_WRITE` | `120/min` | Any mutating request |
| `THROTTLE_READ` | `1000/min` | GET requests |

`development.py` loosens all of these to effectively unlimited so manual API
exploration isn't rate-limited. `test.py` disables throttle classes entirely.

## Tenancy

| Variable | Default | Notes |
|---|---|---|
| `INVITATION_TTL_DAYS` | `7` | |

## CORS / security headers

| Variable | Default | Notes |
|---|---|---|
| `CORS_ALLOWED_ORIGINS` | `[]` | `development.py` sets `CORS_ALLOW_ALL_ORIGINS = True` instead. |
| `DJANGO_SECURE_SSL_REDIRECT` | `True` (prod only) | |
| `DJANGO_HSTS_SECONDS` | `31536000` (prod only) | |

`production.py` additionally forces `SESSION_COOKIE_SECURE`,
`CSRF_COOKIE_SECURE`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`,
and trusts `X-Forwarded-Proto` for SSL detection (`SECURE_PROXY_SSL_HEADER`)
— set these behind a real TLS-terminating load balancer only.

## Intelligence / AI providers

Not environment variables — configured directly in `config/settings/base.py`
as Python dicts, since they're dotted import paths rather than scalars:

```python
INTELLIGENCE_PROVIDERS: dict[str, str] = {}   # empty = deterministic defaults
INTELLIGENCE_AUTO_ACCEPT_CONFIDENCE = 0.9      # confidence >= this auto-applies a suggestion
```

See [`modules/intelligence.md`](./modules/intelligence.md) and
[`EXTENSION_POINTS.md`](./EXTENSION_POINTS.md#adding-an-llm-provider).

## Per-environment overrides

- **`config/settings/development.py`** — `DEBUG=True`, `ALLOWED_HOSTS=["*"]`,
  console email backend, throttles effectively disabled, `django_extensions`
  added (`shell_plus`), `CORS_ALLOW_ALL_ORIGINS=True`.
- **`config/settings/production.py`** — `DEBUG=False`, raises if
  `ALLOWED_HOSTS` unset, forces TLS/HSTS headers, S3 storage by default, JSON
  log formatter. Secret-key *strength* (not just presence) is validated by
  `python manage.py check --deploy`, which CI/CD should run before every
  release.
- **`config/settings/test.py`** — fixed test `SECRET_KEY`/`FIELD_ENCRYPTION_KEY`,
  MD5 password hasher (speed, not security, under test), Celery eager mode,
  LocMemCache, throttling off, in-memory file storage and email backend,
  `CONN_MAX_AGE=0`. Selected automatically by `pytest.ini`
  (`DJANGO_SETTINGS_MODULE = config.settings.test`) — don't override this env
  var when running pytest, it will pull in Redis/throttle behavior the test
  fixtures don't expect.
