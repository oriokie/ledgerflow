# Architecture

## Design principles

- **Domain-Driven Design, one Django app per bounded context.** `tenancy`,
  `users`, `ledger`, `finance`, `budgeting`, `intelligence`, `fx` each own a
  slice of the domain. `common` is the shared kernel every context depends on;
  no other cross-app dependencies are allowed to form a cycle.
- **Service layer, strictly.** Within a module, `services.py` is the only
  place state mutates. Views never call `Model.objects.create()` directly —
  they call a service function, which is `@transaction.atomic`, validates
  invariants, and (for anything financially or operationally meaningful)
  writes an `OutboxEvent` in the same transaction. `selectors.py` is the read
  side: optimized queries returning plain dataclasses, never mutating.
- **API-first.** Every capability is a DRF endpoint under `/api/v1/`; the
  (future) web client is just another consumer. OpenAPI schema is generated
  by drf-spectacular and served at `/api/docs/`.
- **Money is never a float.** `apps.common.money.Money` is an immutable
  value object: integer minor units + ISO-4217 currency, arithmetic only
  within one currency. Every amount in every model is `*_minor: BigIntegerField`.
- **Multi-tenant, shared database, defense in depth.** See
  [Multi-tenancy](#multi-tenancy--row-level-security) below.

## Module dependency graph

```
common  <-- everything depends on this; depends on nothing else in-repo
  ^
  |-- tenancy   (workspaces, RBAC)
  |-- users     (identity, auth)
  |-- ledger    (double-entry core)
       ^
       |-- fx         (exchange rates; ledger doesn't depend on fx yet — cross-currency is a documented seam)
       |-- finance     (depends on ledger + tenancy's Role for permissions)
            ^
            |-- budgeting     (depends on finance.Category, finance.Transaction)
            |-- intelligence  (depends on finance + budgeting selectors)
```

No app imports "downward" — `ledger` knows nothing about `finance`, `finance`
knows nothing about `budgeting` or `intelligence`. Dependencies only point
toward more-foundational contexts.

## Request lifecycle (API)

1. **Middleware** (`apps/common/middleware.py`): assigns/propagates a request
   ID, logs one structured access-log line per request. Tenant resolution is
   deliberately **not** here.
2. **DRF authentication**: `JWTAuthentication` resolves `request.user` from
   the `Authorization: Bearer` header.
3. **`IsTenantMember` permission** (`apps/tenancy/permissions.py`): reads the
   `X-Tenant-ID` header, looks up the caller's `Membership`, checks the view's
   `required_role` or `required_capability`. Sets `request.tenant_id` and
   `request.membership`.
4. **`TenantScopedAPIView.dispatch()`** (`apps/common/api_base.py`) wraps the
   whole request in `transaction.atomic()`, then in `initial()` (which runs
   after auth/permissions) calls `bind_db_tenant()` — `SET LOCAL
   app.current_tenant` — and enters a `use_tenant()` contextvar block. Both
   unwind automatically at `finalize_response()`, even on an exception.
5. **View → service/selector**: the view function is a thin adapter —
   deserialize, call a service or selector, serialize the result.
6. **Exception mapping** (`apps/common/exceptions.py`): one JSON error shape
   for the whole API — `{"error": {"code", "message", "details"}}` — domain
   exceptions (`LedgerError`, `UnscopedAccessError`, ...) are mapped to HTTP
   status explicitly; anything unmapped is a logged 500 with no internals leaked.

Why tenant binding isn't Django middleware: JWT identity is only resolved
inside DRF's `APIView.initial()`, which runs *after* Django's own middleware
chain completes. Plain middleware never sees `request.user` for a
JWT-authenticated request, so tenant resolution has to happen at the DRF
layer — see the docstring in `apps/common/api_base.py`.

## Multi-tenancy & Row-Level Security

Shared database, one schema, isolation enforced in **three independent
layers** so that no single bug is a cross-tenant data leak:

1. **Application layer** — `TenantOwnedModel.objects` (the default manager)
   filters every query by `require_current_tenant_id()`, read from a
   `contextvar`. Querying with no tenant bound raises `UnscopedAccessError`
   rather than silently returning everything.
2. **Save-path guard** — `TenantOwnedModel.save()` refuses to write a row
   whose `tenant_id` doesn't match the active context (`apps/common/models.py`).
3. **PostgreSQL Row-Level Security** — every tenant-owned table has
   `FORCE ROW LEVEL SECURITY` with a policy comparing `tenant_id` to the
   session GUC `app.current_tenant` (`apps/ledger/migrations/0002_financial_integrity.py`).
   **Fail-closed by construction**: `NULLIF(current_setting(...), '')::uuid`
   evaluates to `NULL` when the GUC is unset, and `tenant_id = NULL` is never
   true in SQL — so an unbound connection sees zero rows, not everything.

The GUC is bound with `SET LOCAL`, which is transaction-scoped: it always
unwinds when the transaction ends, even on a crash, and — critically —
`bind_db_tenant()` **raises** if called outside an open transaction, because
`SET LOCAL` outside a transaction is a silent no-op that would otherwise fail
open. Every tenant binding call site (`TenantScopedAPIView`, Celery tasks,
the `tests/utils.py::tenant_scope` test helper) wraps in
`transaction.atomic()` first.

**Not every table is RLS-protected.** `tenancy`'s own `Tenant`/`Membership`/
`Invitation` and `common`'s `OutboxEvent`/`AuditLog` are intentionally
exempt — they're control-plane data written during operations that predate a
tenant context (creating a workspace, accepting an invitation) or are read
cross-tenant by trusted background workers. Isolation for those is enforced
at the service/permission layer instead. `finance.Institution` (bank/aggregator
reference data) is shared reference data, not tenant-owned, so it's exempt too.
See `RLS_TABLES` in the migration for the authoritative list.

## The double-entry ledger

`apps.ledger` is the accounting primitive everything else is built on:
`Account` (asset/liability/equity/income/expense), `JournalEntry` (a balanced
set of `LedgerLine`s), `AccountBalance` (materialized, for O(1) reads).

**One choke point.** `ledger.services.post_journal_entry()` is the only
function that ever writes a `JournalEntry`. It enforces: at least two lines,
all lines share one currency, debits equal credits and are non-zero,
idempotency (a replayed `idempotency_key` returns the existing entry rather
than double-posting), and updates `AccountBalance` in the same transaction.

**Immutable.** `ledger_journalentry` and `ledger_ledgerline` have a database
trigger that raises on any `UPDATE`/`DELETE` — corrections are always a
`reverse_journal_entry()` (the mirror-image entry), never a mutation. This is
enforced in the database, not just the ORM, so it holds even against a raw
SQL bug or a misbehaving admin script.

**How `finance` rides on top.** Every `finance.FinancialAccount` and every
income/expense `finance.Category` owns exactly one backing `ledger.Account`.
Recording an expense is "credit the account's ledger account, debit the
category's ledger account" — the ledger's normal-balance rules make the signs
come out right whether the account is an asset (cash decreases) or a
liability (debt increases). A `finance.Transaction` is the user-facing
aggregate; it denormalizes the signed amount for fast statements but the
`JournalEntry` it points to is the source of truth. See
[`modules/ledger.md`](./modules/ledger.md) and
[`modules/finance.md`](./modules/finance.md) for the full mechanics.

## Events: the transactional outbox

Services that make a change worth telling other systems about write an
`OutboxEvent` row in the **same transaction** as the state change — this
avoids the dual-write problem (you cannot atomically commit to Postgres and
publish to a broker in two separate calls). A Celery beat task
(`apps.common.tasks.relay_outbox`, every 5s) reads unpublished events in `id`
order and calls the configured `EventPublisher`
(`apps.common.publishing`) — logging by default, a Redis Streams example
included, swappable by the `EVENT_PUBLISHER` setting. An event is marked
published **only after** the publisher confirms delivery; a failure stops the
batch (preserving per-aggregate order) and leaves it for retry — at-least-once
delivery, so consumers must dedupe on the immutable `event_id`.

This is distinct from `apps.common.audit.AuditLog`, which is the
human/compliance-facing "who did what" record with a before/after diff, not
an integration mechanism.

## Provider-strategy pattern (AI & automation)

`apps.intelligence` is built so LLMs can be introduced later without
touching any caller. Every AI capability is a `Protocol` (typed interface) in
`protocols.py` plus plain-dataclass DTOs; concrete implementations live in
`providers/` and are resolved by `registry.py` from the `INTELLIGENCE_PROVIDERS`
setting (dotted path per capability, empty dict = deterministic defaults).
Providers speak domain DTOs, never Django models, a prompt, or a vendor SDK
type — so swapping `RuleBasedCategorizer` for an `LLMCategorizer` is a config
change. Every provider output is **advisory**: stored as a suggestion with
confidence + provenance, applied only through the normal finance service
layer after an explicit accept (human or a confidence-threshold auto-accept).
Nothing in `intelligence` ever writes to the ledger directly. See
[`modules/intelligence.md`](./modules/intelligence.md) and
[`EXTENSION_POINTS.md`](./EXTENSION_POINTS.md#adding-an-llm-provider).

## Identifiers, time, and localization

- **UUIDv7 primary keys** everywhere (`apps.common.ids.uuid7`) — time-ordered,
  so B-tree inserts land at the right edge of the index instead of
  fragmenting it like random UUIDv4 would, while staying non-enumerable.
- **All timestamps stored UTC** (`USE_TZ = True`, `TIME_ZONE = "UTC"`);
  localized only at the presentation edge, per-user (`UserProfile.timezone`)
  or per-workspace (`Tenant.default_timezone`).
- **Currency and locale are config, not hardcoded**: `Tenant.base_currency`,
  `default_locale`; `UserProfile.preferred_currency`, `locale`.

## Performance posture

Query patterns are profiled, not assumed — see `scripts/benchmark_queries.py`
and `PERFORMANCE.md` at the repo root for measured before/after numbers. The
short version: aggregate selectors (`net_worth`, `cash_flow`,
`category_breakdown`) are single-query by construction; list endpoints avoid
`select_related` on fields the serializer doesn't read; the transaction table
carries a composite index matching its cursor-pagination sort order so listing
stays a constant-cost index scan regardless of tenant size; slow-changing
analytics (health score, recommendations, anomalies) are cached with
tenant-scoped, version-stamped keys (`apps.common.cache`) that invalidate in
O(1) on any financial write.
