# LedgerFlow — Principal Engineer Production-Readiness Review

Scope: full codebase review of the Django/DRF/PostgreSQL implementation
(~7,350 LOC across 8 apps, 203 tests). This is an assessment against the bar
for putting real people's money data in front of real users, not a code-style
pass. Findings are grounded in the actual source, ordered by severity, and each
carries a concrete recommendation.

**Overall:** the foundation is genuinely strong — the double-entry core,
fail-closed RLS design, per-tenant idempotency, encrypted TOTP secrets, and
well-scoped auth throttling are the parts teams usually get wrong, and here
they're right. The gap to production is not the architecture; it's a handful of
**stubs presented as working systems**, one **latent data bug**, and several
**scaling and operational** items. None are structural rewrites. Roughly
2–3 focused sprints.

---

## P0 — Blockers (must fix before any production traffic)

### P0-1. The outbox relay silently discards every domain event
`apps/common/tasks.py`:
```python
for event in pending:
    # publish(event) -> broker/consumers  (wired per environment)
    OutboxEvent.objects.filter(pk=event.pk).update(published_at=timezone.now())
```
The relay marks events `published_at=now()` **without publishing them**. The
transactional-outbox pattern is implemented correctly on the write side
(events are written in the same transaction as the state change) and then
thrown away on the read side. Any consumer that will ever depend on these
events — notifications, audit export, analytics, webhooks — receives nothing,
and because the row is marked published, the event is **unrecoverable**.

Fix: implement the actual `publish()` to the broker; do **not** mark published
until the broker acks; make the task idempotent and re-drive on failure. Until
a broker exists, leave `published_at` NULL so events accumulate rather than
vanish. This is a correctness bug masquerading as a wiring TODO.

### P0-2. Automation `set_category` by slug is broken
`apps/intelligence/services.py::_apply_action`:
```python
category = (Category.objects.filter(path=action.get("slug")).first()
            or Category.objects.filter(id=action.get("category_id")).first())
```
`Category.path` is a **materialized path** (`"food.groceries"`), not a slug, so
a rule authored with `{"type": "set_category", "slug": "groceries"}` — the exact
shape the docstring in `automation.py` advertises — silently matches nothing and
the transaction is left uncategorized. The service tests only exercised the
`category_id` branch, so the bug shipped green. This is the most-used automation
action and it doesn't work as documented.

Fix: give `Category` a real unique `slug` field (per tenant), match on it, and
add a test that authors a rule the way the docs show. Reconcile the rule schema
(`slug` vs `category_id`) to one documented contract.

### P0-3. `flag_review` is a no-op that reports success
Same file: the `flag_review` action returns `"flagged for review"` but changes
nothing — there is no review-flag field or queue. A user who builds a rule to
flag large transactions for review will believe it's working. Either implement
the flag (a boolean/state on `Transaction` plus a queue view) or remove the
action from `ALLOWED_ACTION_TYPES` until it exists. Shipping an action that
lies about its effect is worse than not offering it.

### P0-4. Half the AI layer is wired to nothing
`get_forecaster`, `get_health_scorer`, `get_anomaly_detector`, and
`get_recommender` are never called outside the registry and their own unit
tests — no selector, task, or endpoint consumes them, and the `intelligence`
app has **no `api/` package** at all. Forecasting, health scoring, anomaly
detection, and recommendations are, from the product's perspective, dead code.
They're well-designed and tested in isolation, which is good, but "built and
tested" was communicated as "delivered."

Fix before claiming these features: add the `intelligence` API (suggestions
list/accept/reject, health score, recommendations, anomalies) and the composing
selectors that build `RecommendationContext`/`HealthInputs` from real reads.
Until then, document them explicitly as **available but not yet exposed**.

---

## P1 — High (fix before scaling past a single node / early users)

### P1-1. Recurring-transaction task is a serial, single-worker loop over all tenants
`apps/finance/tasks.py::run_recurring_transactions` does
`for tenant_id in all_active_tenants: ... materialize_due()`. At "millions of
users" this is one worker walking every tenant sequentially inside one beat
tick — it will not finish within the day it's scheduled for, and a slow tenant
delays all tenants behind it. The per-tenant `try/except` (one failure doesn't
abort the run) is the right instinct; the topology is the problem.

Fix: fan out — beat enqueues one `materialize_due_for_tenant(tenant_id)` task
per tenant (or per shard) onto the queue, so N workers process tenants in
parallel and a poison tenant is isolated to its own task with its own retry.

### P1-2. RLS binding correctness depends on an easily-broken invariant
The isolation guarantee rests on `SET LOCAL app.current_tenant` running **inside
a transaction** (`TenantScopedAPIView.dispatch` opens `transaction.atomic()`
before `initial()` binds). This is correct today. But `SET LOCAL` outside a
transaction is a **silent no-op** — RLS then fails *open* for any code path that
binds without a surrounding transaction (a new management command, a DRF view
that forgets the mixin, a raw script). The design is fail-closed at the policy
level (unset GUC → zero rows), which saves you, but a *mis-set* GUC on a reused
pooled connection is the scarier case.

Fix: (a) add a regression test that asserts a query with no bound tenant
returns zero rows *and* that binding outside a transaction is rejected or
warns; (b) consider `SET` (session) with an explicit `RESET` in a
`finally`, guarded against `CONN_MAX_AGE` connection reuse, or a
connection-pool `reset` hook; (c) add a CI check that every tenant-scoped view
inherits the mixin.

### P1-3. `CONN_MAX_AGE=60` + connection reuse needs a reset guarantee
Persistent connections (`CONN_MAX_AGE=60`) are reused across requests. `SET
LOCAL` unwinds with its transaction so it's safe, but any session-level state
(including a future `SET`) would leak to the next request on that connection.
This is a latent footgun the moment someone adds session-scoped Postgres state.

Fix: document the "transaction-scoped GUC only" rule as an invariant with a
test; if you adopt a pooler (PgBouncer in transaction mode), verify `SET LOCAL`
semantics hold and disable server-side cursors.

### P1-4. No tenant-isolation test for the API layer / fail-closed path
Tests cover service-layer RLS via `tenant_scope`, but there's no test that hits
a real endpoint as tenant A and asserts tenant B's rows are invisible, nor one
that asserts the unbound-tenant path returns nothing. The single most important
security property of a multi-tenant finance app deserves an explicit,
adversarial test at the HTTP boundary.

### P1-5. Known "transient" test flakiness is an unmanaged risk
The suite has a recurring ~16-test failure cluster on Redis-cache-backed auth
tests, currently worked around by restarting Redis. A test suite that needs
infrastructure babysitting to go green will erode trust and hide real
regressions. Root-cause it (connection pool exhaustion? cache key collision
across runs? missing `cache.clear()` between tests?) before launch.

---

## P2 — Medium (maintainability, correctness-in-depth)

- **`models_f_increment()` helper is a code smell.** In `services.py` it returns
  `F("match_count") + 1` from a function that imports `F` locally and is named
  like a verb. Inline it: `AutomationRule.objects.filter(...).update(match_count=F("match_count")+1, ...)`.
- **`suggest_and_maybe_apply` auto-accept is per-transaction with its own
  queries.** Fine for interactive single-transaction use; if it's ever called
  in an import loop it's an N+1 (a categorization query + memory-lookup query
  per row). Add a batch entry point before wiring it to bank import.
- **Automation `add_tag` re-reads and re-writes the full tag set per action.**
  `set_transaction_tags(tags=[*existing, tag])` is O(tags) writes per rule
  match; acceptable now, revisit if rules commonly add many tags.
- **`RecommendationContext`/`HealthInputs` builders don't exist yet.** The
  providers assume a selector will assemble them; that selector is the
  integration seam and is currently missing (see P0-4).
- **Dashboard "safe to spend" and insights are static HTML.** The design is
  documented as grounded in real selectors, but nothing computes them yet — the
  `safe_to_spend` composing selector and the `essential` flag on `BudgetLine`
  are still deferred. Fine as a design artifact; don't confuse it with a
  shipped feature.
- **Materialized `AccountBalance` recompute path.** Confirm every write path
  (post, void, transfer, recurring) updates the materialized balance in the
  same transaction, and add a periodic reconciliation task that recomputes from
  the ledger and alerts on drift — the ledger is truth, the materialization is
  cache, and caches drift.

---

## P3 — Lower (polish, future-proofing)

- FX is a 39-LOC stub; cross-currency transfers/consolidation are deferred.
  Fine, but the `net_worth` selector returns per-currency amounts — make sure
  the UI never sums them naively.
- No API versioning deprecation policy is documented despite the `/api/v1/`
  prefix; define how v2 coexists before you need it.
- OpenAPI schema exists but there's no contract test asserting serializers
  match it; drift is inevitable without one.
- Soft-delete + unique constraints are handled correctly in the spots I checked
  (`condition=Q(deleted_at__isnull=True)`), but audit every unique constraint on
  a `SoftDeletableModel` for the same treatment.
- `bulk_create` bypasses `TenantOwnedModel.save()` tenant stamping — a bug you
  already hit and fixed once. Add a check (a custom manager or a test) so it
  can't regress silently.

---

## What is genuinely good (keep it)

- **Double-entry ledger with a single posting choke point** and append-only
  triggers enforced in the database, not just the ORM. This is the right core.
- **Fail-closed RLS**: unset GUC → `NULLIF(...,'')::uuid` → NULL → zero rows.
  The policy is correct even if the binding invariant (P1-2) needs hardening.
- **Per-tenant idempotency** (`UniqueConstraint(tenant_id, idempotency_key)`) —
  correctly scoped, no cross-tenant collision or leak.
- **Auth**: Argon2, encrypted TOTP secrets, real WebAuthn crypto, scoped
  throttles on the brute-force targets, Redis-backed throttle state (multi-
  worker safe), short access tokens with rotation + blacklist.
- **Provider-strategy AI seam**: the protocol/DTO boundary is the right way to
  keep LLMs out of the execution path; advisory-suggestion storage keeps the
  ledger safe from model error. The seam is real even though the consumers
  (P0-4) aren't built.
- **Transactional outbox on the write side** — correct pattern, just needs its
  read side finished (P0-1).

---

## Recommended pre-production sequence

1. **Sprint 1 — stop the bleeding (P0):** implement outbox publish; fix
   `set_category` slug + `flag_review`; either expose the AI providers via an
   `intelligence` API or re-label them as not-yet-shipped. Add the API-layer
   tenant-isolation + fail-closed tests (P1-4).
2. **Sprint 2 — scale & harden (P1):** fan out the recurring task; harden the
   RLS binding invariant with tests and a CI mixin check; root-cause the test
   flakiness; add the balance-drift reconciliation task.
3. **Sprint 3 — integrate (P2):** build the composing selectors
   (`safe_to_spend`, `RecommendationContext`, `HealthInputs`), wire the
   dashboard to real data, add batch categorization for the bank-import path.

The bones are sound. The work remaining is finishing the systems that are
currently stubbed, proving the isolation guarantees with adversarial tests, and
making the batch/background paths horizontally scalable — in that order.
