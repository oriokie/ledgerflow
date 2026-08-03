# LedgerFlow — Production Performance Optimization

Evidence-driven optimization pass. Every change below was made because a
measurement showed it mattered — profiled with query capture + `EXPLAIN
(ANALYZE, BUFFERS)` against realistic datasets — not on intuition. A permanent
benchmark (`scripts/benchmark_queries.py`) locks the hot paths so a regression
shows up as a number.

## Method

`scripts/benchmark_queries.py` seeds N transactions in a rolled-back
transaction and reports query count + wall time per hot selector; `>3 queries`
is flagged as a likely N+1. `EXPLAIN (ANALYZE, BUFFERS)` verified index usage
on the paginated list query.

**Key finding up front:** the aggregate selectors (`net_worth`, `cash_flow`,
`category_breakdown`, balances) were *already* single-query and N+1-free — the
earlier build did that part right. The wins were in (a) two read paths doing
joins for data nobody used, (b) a missing index for the list's sort order, and
(c) an N+1 in the new health-score selector.

## Database

### Removed unused joins (measured 2–3x faster)
`list_transactions` and `account_statement` both `select_related(...)`'d
category / payee / counter_account, but their serializers read only `*_id`
fields — so every joined row was fetched and discarded.

| Path | Before | After | Change |
|---|---|---|---|
| `list_transactions` (500 rows) | 53.3 ms | 16–19 ms | dropped 4 joins + deferred `metadata` JSON |
| `account_statement` (500 rows) | 38.2 ms | ~18–20 ms | dropped 3 joins |

Both remain 1–2 queries (no N+1); the speedup is pure I/O reduction.

### Added the index the paginated list actually needs
The global transaction list is cursor-paginated on `(-occurred_at, -id)` and
excludes transfers, but no index matched — Postgres index-scanned by tenant
then **top-N sorted the whole tenant**, cost growing linearly with row count.

Added `txn_non_transfer_idx` (partial, `transfer_group IS NULL`) and
`txn_list_cursor_idx` `(tenant_id, -occurred_at, -id)`. `EXPLAIN` on 5,000
rows now shows an **index scan reading 26 rows** (not 5,000) — execution
0.37 ms → **0.13 ms**, and critically **constant** as the tenant grows instead
of linear. This is the change that matters at millions of transactions.

### Fixed an N+1 in the health-score selector
`build_health_inputs` looped over every account calling
`account_current_balance_minor` (one query each). Replaced with the existing
`net_worth()` selector, which computes assets/liabilities in **one** aggregate
over the materialized balances.

### Connection reliability
Added `CONN_HEALTH_CHECKS=True` (validate a persistent connection before reuse,
eliminating stale-connection 500s under `CONN_MAX_AGE>0`) and TCP keepalives so
pooled connections aren't silently reaped by a firewall/LB. Set
`CONN_MAX_AGE=0` in the **test** settings to prevent connection-state bleed
between tests.

## Caching

New `apps/common/cache.py`: **tenant-scoped, version-stamped** analytics cache.

- Keys embed the tenant id and a per-tenant version counter, so a cache key is
  physically un-buildable across tenants, and invalidating *all* of a tenant's
  derived caches is a single `INCR` of that counter — **O(1), no key
  enumeration, no stale-key risk**.
- `apps/finance/signals.py` bumps the tenant version on `post_save` of
  `Transaction`/`AccountBalance`, fired via `transaction.on_commit` so a
  rolled-back write never invalidates. Hooking the models (not each service)
  means a new write path can't forget to invalidate.
- The health-score, recommendations, and anomaly endpoints (read on every
  dashboard load, slow-changing) are now cached (`@cached_analytics`,
  300–600 s TTL as a backstop; the version bump is the real invalidation).

Tests prove cache-hit, tenant isolation, and write-invalidation
(`tests/test_caching.py`).

## Background processing

### Recurring dispatcher: no enqueue storm, bounded memory
The daily beat previously loaded **all** active tenant ids into memory and
enqueued one task each from a single tick. Rewritten to **stream** ids with a
server-side cursor (`.iterator(chunk_size=500)`, O(1) memory) and hand off
fixed-size batches to `dispatch_recurring_batch`, so no single task enqueues an
unbounded number of children. Per-tenant tasks remain isolated with their own
retry (and the earlier UUID-serialization fix stands).

The same per-tenant fan-out powers the balance-drift reconciliation task.

*Documented next tier:* dispatching only tenants **with due templates** needs a
cross-tenant read, which RLS (correctly) fail-closes. The clean solution is a
dedicated `BYPASSRLS` maintenance role used solely by system schedulers — noted
as the follow-up if empty-task volume ever becomes material. (Deliberately not
added now: it introduces a second credentialed DB role and connection config,
and the per-tenant no-op is a single indexed lookup via `recurring_due_idx`.)

## API / serializer efficiency

- List serializer reads `*_id` fields directly (no per-row related access) —
  confirmed N+1-free end to end.
- `.defer("metadata")` keeps the large JSON column out of the list payload it
  never appears in.
- All new intelligence endpoints carry `@extend_schema`, so the OpenAPI schema
  is exact and `check --deploy` is clean.

## Verification

- **226 tests pass** (223 + 3 new caching tests); `ruff`/`black` clean; **no
  migration drift**; `check --deploy` clean; RLS still forced on every
  tenant-owned table (institution reference table correctly exempt).
- `scripts/benchmark_queries.py` — every hot path 1–2 queries, no N+1.
- `EXPLAIN` confirms the paginated list uses the new partial index.

## Deliberately not done (and why)

- **BYPASSRLS scheduler reader** — real value only at very high tenant counts;
  added complexity (second role/credentials) not justified yet. Documented.
- **Read replicas / DB router** — premature; single primary is fine at current
  scale and the app is replica-ready (reads are in selectors).
- **Materialized-view analytics** — the aggregate selectors are already fast;
  revisit only if profiling of a specific report shows a need.
- **Per-endpoint HTTP caching headers / CDN** — belongs at the edge/infra layer,
  not the app.
