# Deployment

## Topology

Four process types, all from the same Docker image (`Dockerfile`, multi-stage
— build tools never ship in the runtime layer):

| Process | Command | Purpose |
|---|---|---|
| `web` | `gunicorn config.wsgi:application` | API + admin |
| `worker` | `celery -A config worker` | Background jobs (recurring postings, reconciliation, outbox relay, invitation emails) |
| `beat` | `celery -A config beat` | Cron-like scheduler that enqueues the periodic tasks below |
| *(migrator)* | `python manage.py migrate` | Run once per deploy, before `web` starts serving |

All four share one PostgreSQL primary and one Redis instance (cache + Celery
broker + result backend). Nothing in the app is in-memory-stateful across
requests — any number of `web`/`worker` replicas can run concurrently.

## Docker

- **`docker-compose.yml`** — local development: Postgres, Redis, `web`
  (runserver, bind-mounted source for live reload), `worker`, `beat`. Not used
  in production.
- **`docker-compose.prod.yml`** — production-*like* local sanity check: real
  gunicorn, no bind mounts, migrations gated behind `RUN_MIGRATIONS=true`,
  secrets from a real `.env` file (never committed). Real deployments should
  use a managed Postgres/Redis and an orchestrator (ECS/Kubernetes/Nomad), not
  this compose file directly — it's for a final pre-ship check.
- **`docker/entrypoint.sh`** — runs before every container start (web, worker,
  beat alike): waits for the database to accept connections (30 × 1s retries),
  then applies migrations if `RUN_MIGRATIONS=true`. Idempotent and safe to run
  concurrently from multiple replicas.
- **Image**: `python:3.12-slim`, non-root `app` user, `HEALTHCHECK` against
  `GET /healthz/`.

Build: `docker build --build-arg REQUIREMENTS_FILE=requirements/production.txt .`

## Migrations

Standard Django migrations, plus one PostgreSQL-only DDL migration
(`apps/ledger/migrations/0002_financial_integrity.py`) that enables Row-Level
Security and the append-only triggers — see `ARCHITECTURE.md`. This migration
no-ops on non-Postgres backends.

Run migrations **before** the new `web`/`worker` code starts serving traffic
— the entrypoint script handles this automatically when `RUN_MIGRATIONS=true`.
For zero-downtime deploys, prefer running migrations as a separate release
step (e.g. a Kubernetes Job / ECS one-off task) rather than relying on the
first container to win the race, especially once the schema has additive-only
migrations that need to land before a rolling deploy of app code that expects
the new column.

## Celery beat schedule

Configured in `CELERY_BEAT_SCHEDULE` (`config/settings/base.py`):

| Task | Schedule | Purpose |
|---|---|---|
| `apps.common.tasks.relay_outbox` | every 5s | Publish committed domain events (near-real-time) |
| `finance.dispatch_recurring_transactions` | daily, 01:00 server time | Fan out recurring-transaction materialization across all active tenants |
| `finance.reconcile_account_balances` | weekly, Sunday 03:00 | Recompute materialized balances from the immutable ledger; logs/corrects drift |

Only **one** `beat` process should run per deployment (it's the scheduler,
not the executor) — running two will double-enqueue everything. `worker`
processes scale horizontally with no such restriction; `finance`'s recurring
and reconciliation tasks are explicitly designed to fan out per-tenant
(`dispatch_recurring_transactions` → `dispatch_recurring_batch` →
`run_recurring_for_tenant`, streamed via a server-side cursor with bounded
batch size) so many workers can process tenants in parallel and one tenant's
failure only retries that tenant.

## Health checks

`GET /healthz/` — liveness only (process is up, can respond), not a deep
dependency check. Point your orchestrator's health probe here. There is no
separate readiness endpoint that checks DB/Redis connectivity; add one before
running behind an aggressive load balancer that needs to distinguish
"starting up" from "ready."

## Scaling notes

- **Web**: stateless, horizontally scalable. `gunicorn --workers 4` is the
  Dockerfile default — tune per instance size; a common starting point is
  `2 × vCPU + 1`.
- **Database**: single primary today. Read replicas / a DB router are a
  documented, deliberately-deferred next step (see `PERFORMANCE.md`) — the
  read side is already isolated in `selectors.py` per module, which is what
  makes adding a router later a routing change, not a rewrite.
- **Cache/broker**: Redis is a single logical instance (`REDIS_URL`); for
  production HA, point it at a managed Redis cluster (ElastiCache, Memorystore,
  Redis Cloud) rather than a single node.
- **Recurring/reconciliation tasks**: already fan out in bounded batches
  (`DISPATCH_BATCH = 500` tenants per sub-dispatch) so they scale with worker
  count, not with a single beat tick's memory. See `apps/finance/tasks.py`.
- **Object storage**: presigned uploads mean the app server never proxies
  file bytes — attachment upload/download bandwidth doesn't scale with your
  web tier at all.

## Pre-release checklist

```bash
python manage.py check --deploy         # settings/security lint
python manage.py makemigrations --check --dry-run   # no un-generated migrations
pytest                                   # full suite (see TESTING.md)
ruff check apps config tests manage.py
black --check apps config tests manage.py
python scripts/benchmark_queries.py      # DEBUG=True, sanity-check hot paths didn't regress
```

`check --deploy` validates production security settings (secret key strength,
`DEBUG=False`, HSTS, secure cookies, `ALLOWED_HOSTS`) — run it against
`DJANGO_SETTINGS_MODULE=config.settings.production` with real-looking env
vars in CI before every release, not just locally.
