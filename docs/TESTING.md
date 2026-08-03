# Testing Strategy

## Running tests

```bash
make test          # == pytest (full suite, with coverage)
pytest tests/test_finance_engine.py -q          # one file
pytest tests/test_finance_engine.py::test_record_expense_posts_balanced_entry -q  # one test
pytest -q --create-db     # force a fresh test DB (after a model/migration change)
```

`pytest.ini` pins `DJANGO_SETTINGS_MODULE = config.settings.test` — **don't**
override this env var when running pytest (e.g. by exporting
`DJANGO_SETTINGS_MODULE=development` in your shell first); `test.py` forces
`LocMemCache`, eager Celery, and `CONN_MAX_AGE=0`, all of which the fixtures
below depend on. Use `development.py` only for `manage.py` commands and
one-off scripts, never for the test run itself.

As of this writing the suite is ~218 tests, all passing, and repeatably green
across consecutive runs with no service restarts required (see "A note on
flakiness" below).

## Layered testing philosophy

Tests target the same layers the code is written in:

1. **Service-layer unit tests** (majority of the suite) — call
   `apps.<module>.services.*` directly inside `tests/utils.py::tenant_scope`,
   assert on the resulting model state. This is where business-rule
   correctness lives (e.g. "an unbalanced journal entry raises," "a transfer
   posts one entry but two transactions"). Fast, no HTTP overhead.
2. **Selector tests** — assert on read-side shape and correctness (e.g.
   `net_worth()` sums per-currency correctly, `account_statement`'s running
   balance matches manual arithmetic).
3. **API tests** — go through the real DRF view + permission + RLS-binding
   stack via `APIClient`, proving the wiring (headers, serializers, status
   codes, and — critically — tenant isolation) actually works end to end, not
   just the service function in isolation.
4. **Adversarial security tests** (`tests/test_review_fixes.py`) — explicitly
   try to break isolation: cross-tenant reads over HTTP, missing membership,
   direct-SQL proof that RLS fails closed with no tenant bound. Every new
   tenant-scoped endpoint should have an equivalent.

## Fixtures & test utilities

`tests/conftest.py` (kept intentionally small — most tests build exactly what
they need via factories):

| Fixture | Provides |
|---|---|
| `api_client` | Bare `APIClient`, unauthenticated |
| `user` | A `UserFactory()` instance |
| `auth_client` | Authenticated `APIClient`, **no** `X-Tenant-ID` — for testing endpoints that don't need one, and the ones that correctly reject its absence |
| `tenant_context` | `(membership, client)` — a user who owns a workspace, plus an authenticated client with `X-Tenant-ID` already set. Covers the common case. |
| `_clear_cache_between_tests` (autouse) | Clears the cache before/after every test — see below |

`tests/utils.py::tenant_scope(tenant_id)` — the service/selector-layer
equivalent of what `TenantScopedAPIView` does for a real request: opens a
transaction, calls `bind_db_tenant()`, enters `use_tenant()`. Any test that
creates or reads RLS-protected rows directly (bypassing HTTP) should use this
rather than the bare `use_tenant()` contextmanager, so it's exercising real
RLS enforcement, not just the Python-side contextvar check.

`tests/factories/` — `factory_boy` factories for the common aggregate roots
(`UserFactory`, `TenantFactory`, `MembershipFactory`, defaulting to `Role.OWNER`).
Prefer building what a test needs via factories + services over a shared
mega-fixture.

## Testing RLS and tenant isolation specifically

Three patterns worth knowing before writing a new tenant-scoped test:

- **Fail-closed proof**: reset the GUC (`RESET app.current_tenant`) and assert
  a direct-SQL count is zero — see
  `test_rls_fails_closed_without_tenant`. Note that inside pytest's own
  wrapping transaction, `SET LOCAL` from an inner `tenant_scope()` can persist
  as a savepoint effect rather than truly unwinding the way it would across
  two real request transactions — if you see cross-test GUC leakage, either
  explicitly `RESET` the GUC or mark the test `@pytest.mark.django_db(transaction=True)`
  so each `transaction.atomic()` is a real transaction. This is a
  test-harness nuance, not a production behavior — in production every
  request/task genuinely is its own transaction.
- **Cross-tenant HTTP isolation**: create two independent
  `MembershipFactory()` instances (different tenants), authenticate a client
  as each, and assert one cannot see the other's data through the API.
- **`bulk_create` tenant stamping**: `bulk_create` bypasses `Model.save()`, so
  it never gets the automatic `tenant_id` stamp — any `bulk_create` call site
  must stamp `tenant_id` explicitly. `test_bulk_created_tags_are_tenant_stamped_and_rls_visible`
  is the regression guard; add an equivalent for any new `bulk_create` call.

## A note on flakiness (and its real cause)

An earlier version of this suite had an intermittent ~16-test failure cluster
in the MFA/WebAuthn/OAuth tests, worked around at the time by restarting
Redis. The actual cause was unrelated to Redis: the test cache backend
(`LocMemCache`) persists across tests within one process, and those flows
store single-use challenges keyed by user id — a challenge from one test could
collide with another's. The fix is the autouse `_clear_cache_between_tests`
fixture in `conftest.py`. If you see intermittent auth-flow failures again,
suspect cache-state bleed before suspecting infrastructure.

## Testing background tasks

`test.py` sets `CELERY_TASK_ALWAYS_EAGER = True` — `.delay()` calls execute
synchronously in-process, no broker required. For tasks that bind a tenant
inside their own `transaction.atomic()` (the recurring/reconciliation
dispatchers), prefer `@pytest.mark.django_db(transaction=True)` so the task's
internal transaction boundary behaves like it would against a real worker
process — see `tests/test_recurring.py::test_scheduler_task_runs_across_tenants`
for the pattern, including why (Celery serializes UUIDs to strings over the
wire, so a task receiving a tenant id must coerce it back to `UUID` before
comparing against the tenant-context guard in `TenantOwnedModel.save()`).

## Testing caching

`tests/test_caching.py` covers: a cached function returns the cached value on
a second call (not recomputed), cache keys are tenant-isolated (two tenants
calling the same cached function get independent results), and a financial
write invalidates the tenant's cache (via `apps.finance.signals`, which fires
on `transaction.on_commit` — use `django_capture_on_commit_callbacks` to
observe this synchronously inside a test transaction that never really
commits).

## What's NOT covered (be aware, contribute here)

- No load/concurrency tests beyond `select_for_update` correctness assertions
  in the ledger posting path.
- No contract test asserting the OpenAPI schema matches serializer reality —
  drift is possible; verify manually via `/api/schema/` after serializer changes.
- Provider-strategy AI code is tested in isolation (pure function tests against
  fixed inputs) plus a thin integration test that the API wiring calls the
  registry correctly — there's no test harness yet for a *real* LLM provider
  (none is implemented), only the deterministic ones.

## Continuous benchmarking

`scripts/benchmark_queries.py` is not a pytest test but a standalone script
(seeds N transactions in a rolled-back transaction, reports query count +
timing per hot selector, flags >3 queries as a likely N+1). Run it after any
change to a selector or serializer touching `finance`/`intelligence` hot
paths: `DEBUG=True python scripts/benchmark_queries.py`.
