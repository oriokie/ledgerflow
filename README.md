# LedgerFlow

Multi-tenant personal finance platform. This README covers the **project
foundation** — architecture, settings, Docker, Celery, testing, CI. See
`SCHEMA.md` for the database design, `AUTH.md` for authentication/MFA/
passkeys/OAuth/orgs/RBAC/invitations, and `FINANCE_ENGINE.md` for the core
financial engine (accounts, transactions, transfers, recurring schedules,
budgets, balances, and financial calculations), and `AI_ARCHITECTURE.md`
for the AI & automation architecture (provider-strategy seam,
advisory-not-autonomous safety model, categorization, forecasting,
health scoring, anomaly detection, recommendations, rule-based automation). The frontend design system —
tokens, components, dashboard/transaction demos, and its accessibility
verification — lives in `frontend/design-system/` and is documented in
`frontend/DESIGN_SYSTEM.md` (intelligent-dashboard IA and insight catalog
in `frontend/INTELLIGENT_DASHBOARD.md`); verify it with
`python scripts/check_design_system.py`.

Everything described here has been run against real PostgreSQL 16 and Redis
7, not just written — see "Verification" at the bottom.

**For the full developer reference** (architecture, every module's domain
model/services/API/permissions, configuration, deployment, testing strategy,
and extension points), see [`docs/README.md`](./docs/README.md) — this
top-level README stays focused on project foundation and CI.

## Project layout

```
apps/
  common/     Money, UUIDv7 ids, tenant context, RLS binding, base models,
              outbox, structured logging, exception handling, pagination
  users/      Custom user model, profiles, MFA, passkeys, OAuth, login audit
              (see AUTH.md)
  tenancy/    Tenant (org/household/personal), Membership, RBAC, invitations
              (see AUTH.md)
  ledger/     Immutable double-entry core (see prior design docs)
  finance/    The financial engine: accounts, categories, transactions,
              transfers, recurring schedules, balances, calculations
              (see FINANCE_ENGINE.md)
  budgeting/  Budgeted-vs-actual overlay (period math, subtree sums, rollover)
  fx/         Exchange rates (seam for multi-currency)

config/
  settings/   base.py -> development.py | production.py | test.py
  urls.py, wsgi.py, asgi.py, celery.py

docker/       entrypoint.sh (migrate/collectstatic/db-wait)
requirements/ base / development / production / test, pinned
tests/        pytest suite + factories + fixtures + a real synthetic
              WebAuthn authenticator (webauthn_fixtures.py)
.github/workflows/ci.yml
```

## Settings architecture

One `base.py` with everything environment-agnostic; `development` /
`production` / `test` each `from .base import *` and override only what
genuinely differs (see the files for exact deltas). Every configurable value
reads from the environment via `django-environ` — see `.env.example` for the
full list. Nothing insecure is silently defaulted: `SECRET_KEY` and
`ALLOWED_HOSTS` have no default and Django's own `check --deploy` gates
secret-key strength.

## Authentication & permissions

Full detail in `AUTH.md`. Summary:

- Custom `users.User` (email as `USERNAME_FIELD`, Argon2 password hashing),
  established before any other migration.
- JWT via SimpleJWT, gated by MFA (TOTP + backup codes) when enabled —
  password login returns a challenge token, not real tokens, until the
  second factor is verified.
- Passwordless login via WebAuthn passkeys, verified with real ECDSA
  cryptography (not mocked) against a hand-built synthetic authenticator in
  tests.
- OAuth (Google/Apple-shaped, config-driven) with PKCE + state, and
  deliberately conservative account-linking (verified email only).
- Organizations/households as a single `Tenant` model with a `type`, RBAC
  via an explicit capability mapping, and invite-then-accept membership
  (never direct add) with hashed, single-use, expiring tokens.
- **Tenant resolution happens at the DRF layer, not Django middleware** —
  JWT identity isn't available until DRF's `authentication_classes` run
  inside `APIView.initial()`, which is *after* Django's middleware chain has
  already completed. See `apps/common/api_base.py` for the full rationale.
  `TenantScopedAPIView.initial()` binds both the Python tenant contextvar
  and the **Postgres RLS session variable** (`SET LOCAL app.current_tenant`)
  for the duration of the request, inside `transaction.atomic()` so the
  `SET LOCAL` is guaranteed to unwind even on an exception.
- `IsTenantMember` resolves `X-Tenant-ID`, checks membership + minimum
  role/capability, and populates `request.tenant_id` — the signal
  `TenantScopedAPIView` acts on.

## Logging

Structured, one-line-JSON in production (`LOG_FORMATTER=json`), readable
console format in development. Every log line carries a `request_id`
(accepted from `X-Request-ID` or minted) propagated via contextvars so it
reaches Celery tasks spawned from a request, and echoed back in the response
header for client-side correlation.

## Error handling

One error envelope for the whole API:
```json
{"error": {"code": "validation_error", "message": "...", "details": {...}}}
```
`apps/common/exceptions.py` maps DRF's own exceptions plus our domain
exceptions (`LedgerError`, `UnscopedAccessError`, ...) into this shape, and
logs anything unrecognized as a genuine 500 without leaking internals.

## Celery / Redis

Broker + backend + retry policy live in `config/settings/base.py`
(`CELERY_*`), shared by web and worker processes. `acks_late` +
`reject_on_worker_lost` so a crashed worker doesn't silently drop a task.
Beat runs the outbox relay every 5 seconds (`apps/common/tasks.py`).

## Testing

`pytest` + `pytest-django` + `factory_boy`, against a **real Postgres test
database** (migrations — including RLS policies and immutability triggers —
run against it, so tests prove real enforcement, not a mock of it).

```bash
make test          # pytest with coverage
make lint          # ruff + black --check
make format        # ruff --fix + black
```

`tests/utils.py::tenant_scope` mirrors exactly what the API layer does
(contextvar + RLS GUC binding) so service-level unit tests can exercise real
RLS without going through HTTP.

## Docker

`docker compose up` — Postgres, Redis, web (runserver, hot reload via bind
mount), worker, beat. `docker-compose.prod.yml` is a production-*like*
overlay (gunicorn, no bind mounts, migrations gated behind
`RUN_MIGRATIONS=true`) for a final sanity check before shipping — real
deployments should target a managed Postgres/Redis and an orchestrator.

The `Dockerfile` is multi-stage: a builder installs deps into a venv, the
runtime image copies only that venv + source and runs as a non-root user.

## Installing & deploying

See [`deploy/README.md`](./deploy/README.md) for step-by-step setup:

- **Mac (local):** `bash deploy/mac-setup.sh` (native venv + Homebrew
  Postgres/Redis) or `bash deploy/mac-setup.sh --docker` (Docker Desktop).
- **Server (automated):** on a fresh Ubuntu VM,
  `sudo DOMAIN=app.example.com ACME_EMAIL=you@example.com bash deploy/provision.sh`
  installs Docker, generates secrets, configures a firewall, and brings up the
  full stack behind a Caddy reverse proxy with automatic Let's Encrypt TLS.
- **Managed infra (K8s/ECS/RDS):** point `DATABASE_URL`/`REDIS_URL` at managed
  services and run the same image; see `deploy/README.md` §3 and
  [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md).

## CI (`.github/workflows/ci.yml`)

`lint` (ruff + black) -> `test` (pytest against real Postgres/Redis service
containers, migration-drift check, coverage artifact) -> `build` (Dockerfile
actually builds). Each stage gates the next.

## Verification

Everything above was run, not just written, in the environment building this
project:
- Full migration set applies cleanly to Postgres 16, including RLS policies
  and append-only triggers.
- `pytest`: **174 passed**, 91% coverage, against the real Postgres test DB —
  see `AUTH.md` and `FINANCE_ENGINE.md` for the domain-specific breakdowns
  (MFA/WebAuthn/OAuth/RBAC/invitations; double-entry postings, transfers,
  recurring schedules, budgets, and financial calculations).
- End-to-end HTTP smoke test (`smoke_test.py`, not part of the CI
  suite — a demo/dev script) through the live Django stack: registration,
  duplicate-email rejection, JWT login, request-ID echo, workspace creation,
  missing-tenant-header rejection, ledger account creation, **cross-tenant
  RLS isolation proven live** (a second tenant sees zero of the first
  tenant's rows), token refresh + rotation, logout blacklist + reuse
  rejection, health check, OpenAPI schema — all passing against the current
  schema (re-run after the auth foundation build, still green).
- A real Celery worker process, connected to a real Redis broker, picked up
  and executed the outbox relay task, the invitation email task, and the
  daily recurring-transaction scheduler (materializing due occurrences,
  correctly RLS-scoped per tenant) asynchronously.
- `ruff check` and `black --check`: clean.
- `manage.py check --deploy` against production settings: **zero issues**.
- `manage.py makemigrations --check`: no drift.
- `requirements/development.txt` installs cleanly in an isolated venv.

## Known follow-ups (deliberately deferred, not forgotten)

- OpenAPI schema for the handful of non-model APIViews is functional but
  could use `@extend_schema` polish for nicer generated docs.
- `common_outboxevent` / `common_auditlog` / `tenancy_invitation` /
  `tenancy_membership` / `tenancy_tenant` are intentionally *not*
  RLS-protected (see the comment in
  `apps/ledger/migrations/0002_financial_integrity.py`) — they're written
  during operations that predate a request-scoped tenant (workspace
  creation, invitation acceptance) and/or read cross-tenant by trusted
  background workers. Revisit with a `BYPASSRLS` worker role if/when a
  tenant-scoped audit-log endpoint ships.
- Production Postgres/Redis are assumed managed (RDS/ElastiCache or
  equivalent) — this repo doesn't provision infrastructure, only the
  application and its container image.
- See `AUTH.md` for auth-specific follow-ups (custom roles, live OAuth
  credentials, SMS MFA, invitation auto-surfacing at registration).
