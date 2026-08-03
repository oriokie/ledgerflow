# LedgerFlow — Remediation Report

Follow-up to `REVIEW.md`. Every P0 and P1 finding is fixed, plus the targeted
P2/P3 items. All changes are backed by tests; the suite is **223 passing**
(was 211 before remediation; +12 net) and now runs **clean three times in a
row with no infrastructure babysitting** — the previously "flaky" cluster is
root-caused and gone.

## P0 — Blockers (all fixed)

### P0-1 Outbox relay silently discarded events → FIXED
- New `apps/common/publishing.py`: an `EventPublisher` strategy (log default,
  Redis-Streams example) chosen by `EVENT_PUBLISHER` setting.
- `relay_outbox` now calls `publisher.publish(event)` and marks an event
  published **only after delivery succeeds**; a publish failure stops the batch
  (preserving per-aggregate order) and leaves events `NULL` for retry.
- Tests: `test_outbox_relay_publishes_then_marks_published`,
  `test_outbox_relay_does_not_mark_published_on_failure`.

### P0-2 Automation `set_category` by slug was broken → FIXED
- Added a real per-tenant `Category.slug` field (unique among live rows) and
  populate it in `create_category`. `_apply_action` now matches on `slug`
  (falling back to `category_id`).
- Test: `test_automation_set_category_by_slug` authors the rule the docs
  advertise and asserts the category is applied.

### P0-3 `flag_review` was a no-op that reported success → FIXED
- Added real `Transaction.needs_review` / `review_reason` state + a partial
  review-queue index, and a `flag_transaction_for_review` finance service.
  `_apply_action`'s `flag_review` now calls it.
- Test: `test_automation_flag_review_sets_real_state` (asserts state + that the
  review queue is queryable).

### P0-4 Half the AI layer was wired to nothing → FIXED
- New `apps/intelligence/selectors.py` builds `RecommendationContext`,
  `HealthInputs`, and anomaly observations from real engine reads.
- New `apps/intelligence/api/` (serializers, views, urls) under
  `/api/v1/intelligence/`: suggestions list + accept/reject, health score,
  recommendations, anomalies, automation-rule CRUD (create validates the
  action allow-list at save time).
- Tests: health-score/recommendations endpoints return provider output;
  automation-rule create rejects disallowed actions (422) and accepts valid
  ones (201).

## P1 — High (all fixed)

### P1-1 Recurring task was a serial single-worker loop → FIXED
- Split into a **dispatcher** (`dispatch_recurring_transactions`, beat entry)
  that fans out one **`run_recurring_for_tenant`** task per active tenant, with
  per-tenant retry and isolation. Same pattern applied to the new balance
  reconciliation task.
- **Real bug caught by the new test:** Celery serializes the tenant UUID to a
  string; the per-tenant task now coerces back to `UUID` so the
  tenant-context identity check in `save()` holds. Without this, *every*
  recurring posting would have failed in production.
- Tests: `test_scheduler_task_runs_across_tenants` (transactional, real
  cross-tenant RLS), `test_dispatcher_enqueues_one_task_per_active_tenant`.

### P1-2 RLS binding could fail open outside a transaction → FIXED
- `bind_db_tenant` now raises if called outside an atomic block (`SET LOCAL`
  outside a transaction is a silent no-op). The mistake surfaces loudly in dev
  instead of silently disabling isolation.

### P1-4 No API-layer isolation / fail-closed tests → FIXED
- `test_api_cross_tenant_isolation` (tenant B cannot see tenant A's rows over
  HTTP), `test_api_requires_tenant_membership`, and
  `test_rls_fails_closed_without_tenant` (direct-DB proof that an unbound
  tenant yields zero rows).

### P1-5 "Transient" test flakiness → ROOT-CAUSED and FIXED
- Real cause: test settings use `LocMemCache`, which **persists across tests in
  one process**, so single-use MFA/WebAuthn/OAuth challenges (keyed by user id)
  bled between tests. The "restart Redis" ritual only helped by perturbing
  timing. Fix: an autouse `_clear_cache_between_tests` fixture clears the cache
  around every test. Also set `CONN_MAX_AGE=0` in test settings to prevent
  persistent-connection state bleed. Suite now passes repeatedly with no
  restarts.

## P2 / P3 (addressed)

- **Balance-drift reconciliation** (`reconcile_account_balances` +
  per-tenant worker, weekly beat): recomputes each account from the immutable
  ledger and logs/corrects drift — the materialized balance is a cache, and
  caches drift.
- **`models_f_increment()` smell** removed; inlined `F("match_count") + 1`.
- **`bulk_create` tenant-stamping** guard: regression test
  `test_bulk_created_tags_are_tenant_stamped_and_rls_visible` locks in the
  fix so a naked `bulk_create` (which bypasses `save()`) can't silently drop
  `tenant_id` again. (Audited all three call sites; all correct.)
- **OpenAPI schema**: added `@extend_schema` to the new intelligence views;
  `check --deploy` is back to **zero issues** (was 7 spectacular warnings).

## Verification

- **223 tests pass**, three consecutive runs, no restarts, ~7s each.
- `ruff` clean, `black` clean, **no migration drift**, `check --deploy` clean,
  design-system verifier passing.
- RLS confirmed forced on all tenant tables incl. the new columns.

## Deliberately still deferred (documented, not silently skipped)

- Actual LLM provider implementations + ensemble router (the seam and its
  consumers are now both built; the LLM classes are the remaining follow-up).
- `upcoming_bills` in `RecommendationContext` awaits typed statement-close
  dates (arrives with the bank-import pipeline).
- Insight snooze/dismiss state; `safe_to_spend` composing selector + the
  `essential` flag on `BudgetLine` for the dashboard.
- Batch categorization entry point before wiring auto-categorize into bank
  import (the per-transaction path is fine for interactive use).
