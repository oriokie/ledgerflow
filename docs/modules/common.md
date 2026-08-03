# `common` — Shared Kernel

Not a bounded context itself — the foundation every other module builds on.
No app-specific business logic lives here; everything is generic enough to
be reused by `tenancy`, `ledger`, `finance`, `budgeting`, and `intelligence`
without creating a dependency cycle.

## Responsibilities

| File | Provides |
|---|---|
| `models.py` | Base model classes: `UUIDModel`, `TimeStampedModel`, `TenantOwnedModel`, `SoftDeletableModel`, plus their tenant-scoped managers |
| `tenant_context.py` | The ambient tenant/actor `contextvar`s (`use_tenant`, `get_current_tenant_id`, `require_current_tenant_id`) |
| `rls.py` | `bind_db_tenant()` — binds the Postgres `SET LOCAL app.current_tenant` GUC |
| `api_base.py` | `TenantScopedAPIView`, `WriteRequiresMemberMixin` — the DRF base classes every tenant-scoped view uses |
| `permissions.py` | Generic, non-tenancy-specific DRF permission classes (`ReadOnly`, `IsVerifiedUser`) |
| `pagination.py` | `CursorPagination` — the default pagination for every list endpoint |
| `exceptions.py` | `api_exception_handler` — the one error shape for the whole API |
| `money.py` | `Money` value object — integer minor units + currency, same-currency-only arithmetic |
| `ids.py` | `uuid7()` — time-ordered UUID primary keys |
| `crypto.py` | Field-level encryption (Fernet) for secrets like TOTP shared keys |
| `storage.py` | Presigned S3 upload URL generation |
| `cache.py` | Tenant-scoped, version-stamped analytics caching |
| `outbox.py` / `publishing.py` / `tasks.py` | The transactional outbox: model, publisher strategy, relay task |
| `audit.py` | `AuditLog` — the human/compliance "who did what" record |
| `logging.py` / `middleware.py` | Structured JSON logging, request-ID correlation |

## Domain model

### Base model hierarchy

```
UUIDModel              id = uuid7() primary key
TimeStampedModel        + created_at / updated_at
TenantOwnedModel        + tenant_id, created_by_id, updated_by_id
                          tenant-scoped managers; save() enforces tenant identity
SoftDeletableModel       + deleted_at, deleted_by_id
                          soft-delete-aware managers; delete() sets deleted_at
```

**Immutable financial records** (`apps.ledger`) inherit `TenantOwnedModel`
directly — never `SoftDeletableModel`. They're corrected by reversing
entries, not deletion, and are additionally protected by a database trigger.
**Mutable domain data** (accounts, categories, transactions, budgets, rules)
inherits `SoftDeletableModel`.

`TenantOwnedModel.save()` is the second isolation layer (after RLS): if
`tenant_id` isn't set, it's stamped from the ambient context; if it *is* set
and doesn't match the ambient context, the save raises `ValueError` rather
than silently writing under the wrong tenant. **This check is bypassed by
`bulk_create`** (which doesn't call `save()`) — any `bulk_create` call site
must stamp `tenant_id=...` explicitly on each instance. See
`apps/finance/tagging.py::set_transaction_tags` for the pattern, and
`tests/test_review_fixes.py::test_bulk_created_tags_are_tenant_stamped_and_rls_visible`
for the regression guard.

### `OutboxEvent`

`id` (BigAutoField, monotonic → ordered relay), `event_id` (UUID, the
consumer-side dedup key), `tenant_id`, `aggregate_type`/`aggregate_id`,
`event_type`, `payload` (JSON), `published_at` (null until delivered).

### `AuditLog`

`tenant_id`, `actor_id` (nullable = system), `action`, `target_type`/`target_id`,
`changes` (JSON before/after diff), `context` (JSON — ip, user agent, request
id). Append-only, protected by the same immutability trigger as the ledger.

## Key mechanisms

### Tenant context & RLS binding

See [`../ARCHITECTURE.md#multi-tenancy--row-level-security`](../ARCHITECTURE.md#multi-tenancy--row-level-security)
for the full three-layer explanation. The short version: `use_tenant(tenant_id)`
sets a `contextvar` that the ORM managers read; `bind_db_tenant(tenant_id)`
sets the Postgres session GUC that RLS policies read. Both must be active for
a tenant-scoped read/write to succeed; `bind_db_tenant` **raises** if called
outside an open transaction (`SET LOCAL` outside a transaction is a silent
no-op that would otherwise fail open).

### Caching (`cache.py`)

Tenant-scoped, version-stamped keys: `analytics:{name}:{tenant}:v{N}:{digest}`.
`invalidate_tenant(tenant_id)` bumps the per-tenant version counter — an O(1)
operation that instantly orphans every cached key for that tenant, no
enumeration needed. `@cached_analytics(name, ttl)` decorator wraps a slow,
tenant-scoped, slow-changing computation. See
[`../modules/intelligence.md`](./intelligence.md) for how this is used, and
`apps/finance/signals.py` for how writes trigger invalidation.

### Money

`Money(amount_minor: int, currency: str)` — frozen dataclass, `__post_init__`
validates the currency is ISO-4217 alpha-3 uppercase. `+`/`-`/unary `-` only
between same-currency values (`CurrencyMismatchError` otherwise). `from_decimal()`
and `to_decimal()` are the only places conversion to/from human-readable
decimal happens — everywhere else in the system, amounts are `*_minor: int`.

### Outbox & event publishing

Write side: any service that changes something worth telling other systems
about creates an `OutboxEvent` in the same transaction as the state change.
Read side: `apps.common.tasks.relay_outbox` (Celery beat, every 5s) publishes
unpublished events in order via the configured `EventPublisher`
(`EVENT_PUBLISHER` setting), marking `published_at` only after confirmed
delivery. See [`../ARCHITECTURE.md#events-the-transactional-outbox`](../ARCHITECTURE.md#events-the-transactional-outbox).

## Configuration

`FIELD_ENCRYPTION_KEY`, `EVENT_PUBLISHER`, `DB_CONN_MAX_AGE`, `REDIS_URL`,
`LOG_LEVEL`/`LOG_FORMATTER` — see [`../CONFIGURATION.md`](../CONFIGURATION.md).

## Extension points

- New `EventPublisher` implementations (broker integrations) — see
  [`../EXTENSION_POINTS.md#adding-an-event-consumer`](../EXTENSION_POINTS.md#adding-an-event-consumer).
- New base-model mixins should compose with the existing hierarchy, not
  replace it — e.g. a future `VersionedModel` mixin would sit alongside
  `SoftDeletableModel`, not fork it.

## Testing

`common` has no `tests/test_common.py` of its own — its guarantees (tenant
isolation, RLS fail-closed, cache invalidation) are proven by every other
module's tests exercising it, plus the dedicated adversarial suite in
`tests/test_review_fixes.py` and the caching suite in `tests/test_caching.py`.
