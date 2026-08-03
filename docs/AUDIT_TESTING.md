# LedgerFlow — Testing Review

**Measured, not estimated.** Coverage was run with `pytest-cov` and `vitest
--coverage`; endpoint reach was counted by cross-referencing test files against
the URL resolver.

| | Value |
|---|---|
| Backend line coverage | **88%** (15,378 statements, 1,782 uncovered) |
| Backend files at 100% | 87 |
| Backend tests | 1,266 across 68 files |
| Frontend line coverage | **56%** |
| Frontend tests | 637 across 104 files |
| API endpoints referenced by tests | 165 of 202 |

**The headline number is not the finding.** 88% backend coverage is genuinely
good, and the money-critical modules are the best-covered part of the codebase.
The risk is concentrated in three specific layers that the aggregate hides, and
in one habit (§6) that has already let real bugs through a green suite.

---

## 1. Where the coverage is, and where it isn't

Money handling — the part that must not be wrong — is well covered:

| Module | Coverage |
|---|---|
| `billing/invoicing.py` | 96% |
| `finance/reconciliation.py` | 94% |
| `ledger/services.py` | 93% |
| `finance/services.py` | 90% |
| `billing/dunning.py` | 88% |
| `billing/promotions.py` | 88% |
| `billing/refunds.py` | **82%** |

Refunds being the weakest of these is worth noting: it is the only module in
the list that moves money *out*, and its uncovered lines are concentrated in
`_execute` and `_fail` — the provider-error branches.

The weak areas are not distributed randomly. They form three groups.

### Group 1 — Celery tasks are systematically untested

| Module | Coverage | Statements |
|---|---|---|
| `platform_admin/tasks.py` | **0%** | 57 |
| `receipts/tasks.py` | 39% | 23 |
| `goals/tasks.py` | 62% | 42 |
| `notifications/tasks.py` | 62% | 93 |
| `finance/tasks.py` | 64% | 77 |
| `intelligence/tasks.py` | 65% | 51 |

Every scheduled task in the platform module — the dunning sweep, usage
snapshots, impersonation expiry, the alert sweep — has **zero** test coverage.
These run unattended against production data with no user watching, which is
precisely the profile of code that most needs a test and least gets one. A task
that silently does nothing looks identical to a task that has nothing to do.

`finance/tasks.py` at 64% is the sharpest instance: it contains
`reconcile_balances_for_tenant`, the job that detects a customer's materialised
balance diverging from the ledger. The detection logic is partly untested.

### Group 2 — the platform console's view layer

`platform_admin/api/views.py`: **51% coverage, 302 uncovered statements** — the
single largest hole in the codebase.

The asymmetry is instructive. The platform *services* and RBAC are heavily
tested (34 RBAC tests, 51 operations tests), because that is where I judged the
risk to be. The view layer that exposes them is half-tested, and only 14 of 46
platform endpoints appear in any test. So the authorisation rules are proven
and the wiring that applies them is substantially not.

### Group 3 — the frontend's integration layer

The frontend aggregate of 56% conceals a much sharper split:

| Area | Lines | **Functions** |
|---|---|---|
| `src/ui` | 93% | 81% |
| `src/lib` | 81% | 79% |
| `src/pages` | 50% | 26% |
| `src/api` | 40% | **5%** |
| `src/hooks` | 18% | **23%** |
| `src/components` | 21% | 60% |

**5% function coverage on `src/api`** means almost every API method in the
client is never called by a test. Hooks are at 23%.

The pattern is that testing effort went to the design system and pure utilities
— the parts that are easy to test and rarely wrong — and largely skipped the
layer that talks to the server, which is where behaviour actually lives and
where the F-1 export bug lived undetected.

---

## 2. Missing unit tests

* **Provider failure paths.** `billing/refunds.py` `_execute`/`_fail` and
  `stripe_provider.py` (68%) have untested error branches. What happens when
  Stripe returns a 500 mid-refund is a question with real money attached.
* **`intelligence/signals.py` (36%)** — the categorisation signal handlers.
  Wrong categorisation is silent and compounding.
* **`intelligence/llm.py` (67%)** — prompt construction and response parsing.
  A malformed model response should degrade, not crash.
* **`notifications/summary.py` (70%)** — the monthly email. It runs once a
  month, unattended, against every tenant; a failure is discovered by its
  absence.
* **No property-based tests.** `hypothesis` is not a dependency. Money
  arithmetic is the textbook case for it: invoice totals
  (`subtotal − discount − credit + tax`), refund balance accumulation, payoff
  amortisation and FX conversion are all functions with invariants that should
  hold for *any* input, and are currently tested on a handful of chosen ones.
  The invoice-arithmetic bug found in the earlier audit — the one where two
  money colours had less than 1.0 of headroom — was found by computing across a
  range, not by an example.

## 3. Missing integration tests

* **37 of 202 endpoints are never touched.** Concentrated in `platform` (14 of
  46 tested), `goals` (4), `budgeting` (4), `fx` (2), `ledger` (1).
* **No webhook integration tests** driving a realistic provider payload
  end-to-end — signature verification, idempotent replay, and the state
  transitions that follow.
* **Transaction-boundary tests are thin.** After the D-1 fix there is one
  `on_commit` test. There is no test that a failure *mid-service* rolls back
  cleanly — e.g. an invoice created, then the payment provider throwing.
* **Only 9 query-count assertions across 5 files.** For a product with heavy
  list views (transactions, tenants, audit, reports) that is thin. N+1
  regressions are invisible until they are a production incident, and the three
  places I did assert query counts were all places I had just written.

## 4. Missing end-to-end tests

`scripts/ui_smoke.py` drives real Chromium across 17 screens and fails on
console errors or blank pages. That is real and it caught real problems. But it
asserts that pages **render**, not that they **work**.

There is no test that walks a user journey:

1. Register → verify → create workspace → add account → import CSV → categorise
   → set a budget → see the budget reflect the spend.
2. Invite a member → accept → confirm the role limits what they can do.
3. Subscribe → payment fails → dunning opens → retry succeeds → access restored.
4. Reconcile a statement to zero.

Each of these crosses four or five modules, and each is a sequence where every
individual step has passing tests. The invitation flow is the proof: `create_invitation`
was tested, `send_invitation_email` was tested, `AcceptInvitePage` was tested — and
the flow was broken end to end in two independent ways, because nothing tested
the *seam*.

Also absent: **no contract test** between the generated OpenAPI schema and the
TypeScript client. The schema is generated and the client is hand-written; a
field rename would be caught at runtime, in the browser, by a user.

## 5. Untested edge cases

* **Concurrency.** Locks were added for D-4 and D-5, and both are verified by
  asserting `select_for_update` appears in the source — not by racing two
  transactions. That tests that the fix is *present*, not that it *works*.
  Postgres-backed concurrency tests are awkward but not hard, and this is the
  category where the earlier audits found the most real defects.
* **Boundary money values.** Zero-amount transactions, the largest value that
  fits in a `BigIntegerField`, currencies with no minor unit (JPY, KES has 2 but
  UGX has 0). Rounding at the half-cent is tested for invoices and not for FX.
* **Timezone boundaries.** A transaction at 23:59 in Nairobi belongs to a
  different day than in UTC. `default_timezone` is per-workspace; nothing tests
  a report at a day boundary across zones.
* **Soft-delete interactions.** Deleting a category that has transactions,
  a payee referenced by a rule, an account with a debt profile.
* **Partial failure in batch operations.** The reconciliation endpoint rejects
  the whole batch if one id is unknown, and there is a test for that — but bulk
  categorisation and bulk automation decisions have no equivalent.
* **Very large workspaces.** No test creates 10,000 transactions and asserts
  the transaction list, budget status or a report still respond. Every
  performance property in this system is currently unmeasured.

## 6. Regression risks — the sharpest finding

**Three tests in this codebase asserted the buggy behaviour and had to be
rewritten when the bug was fixed:**

| Test | Asserted |
|---|---|
| `test_invitation_email_is_sent` | that the email was dispatched inline — the race |
| `ReportCard.test.tsx` | *"offers a plain download link"* — the 401 |
| `DebtAnalytics.test.tsx` | *"offers the schedule as a plain download link"* — the 401 |

These are not careless tests. They are precise, readable, and they passed. The
problem is that they were written **from the implementation rather than from
the requirement**: "there is an anchor with a download attribute" instead of
"the user ends up with a CSV file". The implementation detail was the bug, so
the test locked it in.

That is the highest-value thing to change about how this suite is written, and
it costs nothing: assert the outcome the user gets, not the mechanism that
delivers it. `downloadFile` was called with the right path is better than an
anchor exists; the invitee received an email containing a working link is
better than delay() was called.

**Two further risks:**

* **Coverage of a wrong thing still reads as green.** `RECONCILED` was read by
  two selectors that were themselves covered, and written by nothing. Coverage
  cannot see an unreachable state; only a journey test would have.
* **The suite could not run twice** until the `--reuse-db` / transactional-test
  interaction was fixed. That class of problem — tests that pass in CI and fail
  locally — erodes trust in the suite faster than any individual failure, and
  is worth a periodic "run it twice" check in CI.

---

## 7. What is genuinely strong

Worth stating, because it determines how much the above costs to fix:

* **1,266 backend tests, 88% coverage, 87 files at 100%.** That is well above
  what most products carry at launch.
* **Money paths are the best-covered part of the codebase**, which is the
  correct priority.
* **Tests are written as behaviour, not mechanics** — names like
  `test_in_flight_refunds_count_against_the_refundable_balance` and
  `test_a_suspended_case_still_progresses_to_abandonment` describe the property
  under test, so a failure tells you what broke rather than what line changed.
* **The regression discipline works.** Fixes were verified by reverting them
  and confirming the suite went red on exactly the right tests — that is how
  the invoice-arithmetic and over-refund guards were validated.
* **Security is tested adversarially** — 37 tests written as attacks, including
  RLS fail-closed behaviour verified with raw SQL.

---

## 7b. Delivered since this review

| Item | Result |
|---|---|
| **1. Four end-to-end journeys** | `tests/test_journeys.py` — import→budget, invite→role limits, payment failure→recovery, statement reconciliation |
| **2. Assertion habit** | The journeys assert outcomes: *the invitee received an email whose link resolves to a declared route*, not *delay() was called* |
| **3. Celery tasks** | `tests/test_scheduled_tasks.py` — `platform_admin/tasks.py` **0% → 96%**, `finance/tasks.py` **64% → 86%** |

Backend total 88.4% → **88.9%**, 1,266 → **1,283** tests. The total moved
little because these targeted small modules; the point was never the aggregate.

Two things the new tests demonstrate rather than assert:

* **The invitation journey needs `django_capture_on_commit_callbacks` to see
  the email at all.** Having to opt into commit hooks *is* the evidence that
  dispatch is deferred rather than inline — the property the D-1 fix
  established, now enforced by a test that would fail if it regressed.
* **The beat-schedule test needs `app.loader.import_default_modules()`.**
  Without it, `app.tasks` in a test process is nearly empty and the assertion
  passes vacuously — a check that cannot fail is worse than no check, so the
  test forces discovery before asserting every scheduled task name resolves.

**4/7 — the contract test, and a deliberate substitution.** The plan was to
raise `src/api` off 5% *function* coverage. Inspecting it changed the
recommendation: `client.test.ts` already covers the parts with logic — error
shapes, header injection, the 401 refresh-retry, 204 handling — and the
uncovered remainder is 150 thin wrappers of the form
`() => api.get("/debt/debts/")`. Testing those asserts that a string literal
equals a string literal. It would move the number and find nothing.

The failure those wrappers actually suffer is **drift from the backend**, which
no unit test of the wrapper can see. So `tests/test_api_contract.py` checks that
instead: every path literal in the TypeScript client must resolve to a real
Django route. 187 assertions, one per path.

Proven against the bug it exists for — reintroducing F-1's `/api/v1` prefix in
`reports.ts` turns the suite red immediately.

Three parser problems had to be solved before it said anything true, and each
had first produced a convincing false failure:

* **Nested interpolations.** `${qs({ from, to })}` contains an object literal,
  so a naive `\$\{[^}]*\}` stops at the inner brace and leaves `)}` on the path.
* **Trailing interpolations are query strings, not segments.** This client
  writes `` `/finance/transactions/${qs(filters)}` ``; treating that like an id
  produced eight phantom "missing route" failures.
* **Module constants.** `platform.ts` builds every route as `${BASE}/tenants/`,
  so before resolving `const BASE` **all 46 console endpoints were invisible** —
  the test passed while checking nothing about the largest part of the API.

The last of those is the one worth remembering: a contract test that silently
skips a module is worse than none, so `test_the_client_actually_has_paths_to_check`
and a `> 20 platform paths` floor now fail if the extractor ever goes quiet.

**5/6/8 — the remainder.**

| Item | Result |
|---|---|
| `platform_admin/api/views.py` | **51% → 88%.** 62 tests through the router, so the capability gate, serializer, service call and response shape are exercised together |
| Property-based money tests | `tests/test_money_properties.py` — 14 invariants over generated inputs, with `hypothesis` added to `requirements/test.txt` |
| Performance | `tests/test_performance.py` — marked `slow`, excluded by `-m "not slow"` |

Backend **88.9% → 90.9%**, 1,283 → **1,554 tests**.

### The first measured performance characteristic

| Endpoint | Small | Large | Scales? |
|---|---|---|---|
| Transactions list | 6q | 6q | flat |
| Accounts list | 7q | 7q | flat |
| Health score | 12q | 12q | flat |
| Platform tenant directory | 11q (3 tenants) | 11q (23) | flat |
| Reconcile 200 rows | 10q | — | flat |
| **CSV import** | **15.5 q/row** | **15.1 q/row** | linear |

Everything is flat in row count, which is the property that separates slow from
unscalable. The finding is the import constant: ~15 queries per row is
*linear* — the important part — but not cheap, because each row is a real
ledger posting (journal entry, lines, account lock, balance update, dedupe
check). A year of statements is ~30,000 queries, and the measured 80-row batch
already takes a second. Fine for occasional CSV use; **not** fine for a nightly
bank-feed sync, which is the G-1 build. The constant is now pinned by an
assertion so it cannot drift upward unnoticed.

### Two vacuous tests, caught before they were trusted

* **The performance suite initially reported 0 queries everywhere and passed.**
  `reset_queries()` ran before `len(captured)` was read, and
  `CaptureQueriesContext.__len__` slices `connection.queries` — so every
  measurement was zero and every assertion passed against nothing.
* **The contract test initially skipped all 46 platform endpoints** because
  `platform.ts` builds paths from a `${BASE}` constant.

Both are the same failure: a check that cannot fail. Each now carries a floor
assertion that fails if the measurement goes quiet.

### Payload contract and real concurrency

| Item | Result |
|---|---|
| Payload drift | `tests/test_payload_contract.py` — every field a TypeScript interface declares **required** must arrive in the live response |
| Concurrency | `tests/test_concurrency.py` — eight threads on separate connections, racing the locks instead of grepping for them |

**A real bug, found by actually racing it.** `ledger.post_journal_entry`
recovered from a lost idempotency race with:

```python
except IntegrityError:            # lost an idempotency race — return the winner
    return JournalEntry.objects.get(idempotency_key=idempotency_key)
```

That cannot work. A unique-constraint violation aborts the *enclosing*
transaction, so the recovery query raises `TransactionManagementError` instead
of returning the winner. The guarantee held for the sequential replay case —
which every existing test exercised — and broke under the concurrent case it
exists for. Two payment webhooks arriving together would have produced an
error rather than one entry.

Fixed by wrapping the insert in its own savepoint. Verified by removing the
savepoint and watching the race fail, then restoring it.

**Design notes on the concurrency suite**, because these are easy to get wrong
and end up testing nothing:

* `transaction=True` is mandatory — the default wrapping transaction never
  commits, so a second connection sees no setup and every race passes trivially.
* Each thread closes its connection, or the pool exhausts and teardown hangs.
* A `Barrier` releases the threads together; without it they run sequentially by
  luck.
* **A control test performs the same eight-way race without a lock and asserts
  the counter *does* lose updates.** If the unlocked version were also correct,
  the harness would not be producing real concurrency and every other assertion
  in the file would be meaningless.

Direction matters in the payload contract: a field the backend **dropped** that
TypeScript requires is asserted, because it breaks the client at runtime. A
field the backend **added** is reported and not asserted — failing on it would
make every additive change a frontend chore, and a test people routinely weaken
stops being a test.

Backend **1,592 tests**.

Still open: generated types from the OpenAPI schema would check field *types*,
not just names — this catches `amount_minor` disappearing, not `amount_minor`
becoming a string. And these remain characterisation tests, not load tests:
eight threads for a moment says nothing about sustained throughput or lock
contention under production traffic.

## 8. Recommended order

1. **Four end-to-end journey tests** (§4). Highest value per hour by a wide
   margin: the two most expensive bugs found in these audits were both seam
   failures that unit tests could not see.
2. **Change the assertion habit** (§6). Free, and it prevents the class of bug
   that has already occurred three times.
3. **Test the Celery tasks**, starting with `platform_admin/tasks.py` at 0% and
   `finance/tasks.py`'s drift detection.
4. **Raise `platform_admin/api/views.py` off 51%** — 302 uncovered statements
   in the console that operates the business.
5. **Frontend hooks and API client.** 5% function coverage on `src/api` is the
   layer where F-1 hid.
6. **Add `hypothesis`** for money arithmetic invariants.
7. **A contract test** between the OpenAPI schema and the TypeScript client.
8. **A load test** — nothing in this system has a measured performance
   characteristic.

Items 1 and 2 are days and address the failures that actually occurred. The
rest is steady coverage work that can proceed in parallel.
