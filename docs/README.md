# LedgerFlow Developer Documentation

LedgerFlow is a multi-tenant, API-first personal finance platform built on
Django + Django REST Framework + PostgreSQL. This directory is the
engineering reference: how the system is put together, how to work in each
module, and how to run and extend it.

## Start here

| Doc | Read this for |
|---|---|
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | System design: DDD module map, multi-tenancy, the double-entry ledger, event pipeline, provider-strategy pattern |
| [`PERMISSIONS.md`](./PERMISSIONS.md) | Auth, RBAC roles/capabilities, Row-Level Security mechanics |
| [`CONFIGURATION.md`](./CONFIGURATION.md) | Every environment variable / setting, grouped by concern |
| [`DEPLOYMENT.md`](./DEPLOYMENT.md) | Docker topology, migrations, Celery beat, scaling notes |
| [`TESTING.md`](./TESTING.md) | Test strategy, fixtures, conventions, how to run |
| [`EXTENSION_POINTS.md`](./EXTENSION_POINTS.md) | The seams designed for extension: AI providers, automation actions, account types, event consumers |

## Modules

Each module doc covers: purpose, domain model, service layer, key workflows,
API surface, permissions, module-specific configuration, extension points,
and testing.

| Module | Responsibility |
|---|---|
| [`common`](./modules/common.md) | Shared kernel: base models, tenancy context, RLS binding, money, caching, outbox, logging |
| [`tenancy`](./modules/tenancy.md) | Workspaces, memberships, RBAC, invitations |
| [`users`](./modules/users.md) | Identity: auth, MFA (TOTP), WebAuthn/passkeys, OAuth |
| [`ledger`](./modules/ledger.md) | The immutable double-entry accounting core |
| [`finance`](./modules/finance.md) | The user-facing domain layer: accounts, categories, transactions, transfers, recurring, splits, bills, import/export, attachments |
| [`budgeting`](./modules/budgeting.md) | Budgets and actual-vs-budget reporting |
| [`intelligence`](./modules/intelligence.md) | AI/automation: categorization, forecasting, health score, anomalies, rules |
| [`mobile`](./modules/mobile.md) | PWA: receipt scanning, Quick Add, offline sync, push notifications, biometric login |
| [`automation`](./modules/automation.md) | Automation engine: merchant normalisation, seven detectors, learning loop, review queue |
| [`analytics`](./modules/analytics.md) | Reporting platform: 14 dashboards over shared filters, caching, export and rendering |
| [`debt`](./modules/debt.md) | Debt planner: terms, snowball/avalanche payoff simulation, schedules, alerts |
| [`investments`](./modules/investments.md) | Portfolio tracking: lots, cost basis, realised/unrealised gains, allocation, valuation history |
| [`ai-coach`](./modules/ai-coach.md) | AI financial coach: stored insights, scoring, briefings, and the LLM provider seam |
| [`cashflow-calendar`](./modules/cashflow-calendar.md) | Day-by-day liquid balance projection: overdraft prediction, recurring/bill expansion, calendar UI |
| [`goals`](./modules/goals.md) | Financial goals: taxonomy, forecasting engine, success probability, auto-contribution, recommendations |
| [`notifications`](./modules/notifications.md) | Notifications & alerts (budget, bills, anomalies, goals) |
| [`fx`](./modules/fx.md) | Exchange rate reference data |

## Codebase orientation

```
apps/<module>/
  models.py        domain models (see each module doc)
  services.py       the ONLY place state mutates — views never write models directly
  selectors.py       read-side: optimized queries, no mutation
  tasks.py            Celery background jobs (where applicable)
  api/
    serializers.py, views.py, urls.py     DRF layer, mounted under /api/v1/<module>/
  migrations/
tests/
  test_<module>*.py  service/selector/API tests
  factories/          shared model factories
config/
  settings/            base.py + development.py / production.py / test.py
  urls.py, celery.py
```

**Read/write split.** Every module follows the same rule: `services.py`
functions are the only way state changes (each is `@transaction.atomic`,
each emits an `OutboxEvent`, each is independently testable without HTTP).
`selectors.py` functions are pure reads, written to avoid N+1 queries
explicitly. Views call services and selectors; they never touch models
directly. This is the service-layer discipline referenced throughout every
module doc.

## Quick start

```bash
cp .env.example .env            # fill in DATABASE_URL, REDIS_URL, FIELD_ENCRYPTION_KEY, DJANGO_SECRET_KEY
make install                    # pip install + pre-commit hooks
make migrate
make run                        # http://localhost:8000, API at /api/v1/, docs at /api/docs/
make worker                     # separate terminal: Celery worker
make beat                       # separate terminal: Celery beat (recurring, reconciliation, outbox relay)
make test                       # full suite
```

Or `docker compose up --build` for the whole stack (Postgres, Redis, web,
worker, beat) with no host installs. See [`DEPLOYMENT.md`](./DEPLOYMENT.md).

## Keeping these docs accurate

These docs describe **behavior grounded in the current source** — file paths,
function names, and settings referenced here should exist verbatim. When a
module's public contract changes (a new service function, a new setting, a
changed permission), update the corresponding doc in the same PR. Docs that
drift from code are worse than no docs; prefer deleting a stale paragraph
over leaving it.

See also [`FRONTEND_REVIEW.md`](../FRONTEND_REVIEW.md) for a functional audit of every frontend page and the error-boundary gap it found.
