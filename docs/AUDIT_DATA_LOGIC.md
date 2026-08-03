# LedgerFlow — Data & Business Logic Audit

**Scope:** business rule consistency, data integrity, validation, race
conditions, duplicate-data risk, transaction handling, audit logging, error
recovery.

**Method:** static analysis, live probing against a seeded database, and
inspection of every `@transaction.atomic` service, every Celery dispatch site,
and every database constraint. Findings were confirmed by reading the executing
code path, not inferred from naming.

**Verdict.** The financial core is genuinely well built — the ledger is one of
the more carefully implemented double-entry engines I have reviewed, and §7
says so specifically. The defects are concentrated at the **edges**: where the
system hands work to a background worker, where it builds a URL for an email,
and where it was supposed to write down what a user did.

One finding (D-3) is a stated product principle that is not implemented at all.

---

## Severity summary

| ID | Severity | Area | Issue | Status |
|---|---|---|---|---|
| D-1 | **High** | Transaction handling | Invitation email dispatched before commit | **Fixed** |
| D-2 | **High** | Business logic | Invitation links point at a nonexistent page | **Fixed** |
| D-3 | **High** | Audit logging | Tenant audit log has zero write sites | **Fixed** |
| D-4 | Medium | Race condition | Learning-store lost updates | **Fixed** |
| D-5 | Medium | Race condition | Plan-limit checks are check-then-act | **Fixed** |
| D-6 | Low | Error recovery | Drift logged but not surfaced to an operator | **Fixed** |

---

## D-1 — HIGH: invitation email dispatched inside the transaction

`apps/tenancy/services.py:304`, inside `@transaction.atomic`:

```python
send_invitation_email.delay(invitation_id=str(invitation.id), raw_token=raw_token)
return invitation, raw_token
```

The task is queued **before the transaction commits**. A Celery worker is a
separate process on a separate connection; it can dequeue and run before the
row is visible. The task then does:

```python
except Invitation.DoesNotExist:
    return  # invitation was revoked/deleted before the task ran
```

The comment names a rare cause and misses the common one. The sequence is:

1. Transaction opens, `Invitation` row created (uncommitted)
2. Task queued
3. Worker dequeues, queries — row not visible
4. `DoesNotExist` → **`return`, silently**
5. Transaction commits; the invitation now exists

The inviter sees success. The invitee receives nothing. **No error, no log, no
retry, no trace.** The invitation sits `PENDING` until it expires.

If the surrounding transaction *rolls back*, the failure inverts: the email may
already have been sent carrying a token for an invitation that will never exist.

The codebase already knows the correct pattern —
`apps/receipts/services.py:98` does exactly this:

```python
transaction.on_commit(lambda: process_receipt.delay(str(receipt.id)))
```

**Fix:** wrap the dispatch in `transaction.on_commit`. One line. Additionally,
the task's `DoesNotExist` branch should log a warning rather than returning
silently — a genuinely revoked invitation is worth a line in the log, and had
that log existed this bug would have been visible from day one.

> Secondary note: the raw invitation token is passed as a task argument, so it
> is serialised into Redis in plaintext and persists in the queue. The token is
> hashed at rest in Postgres precisely so a database dump is not a set of live
> credentials; the broker undoes that. Passing only `invitation_id` and
> regenerating the link inside the task would close it.

## D-2 — HIGH: invitation links are broken

`apps/tenancy/tasks.py:20`:

```python
accept_url = f"{settings.OAUTH_REDIRECT_URI.rsplit('/', 1)[0]}/invitations/accept?token={raw_token}"
```

With the shipped default `OAUTH_REDIRECT_URI = "http://localhost:3000/auth/callback"`:

```
  email builds : http://localhost:3000/auth/invitations/accept?token=XXX
  page lives at: http://localhost:5173/invite?token=XXX
```

Three independent faults in one line:

1. **Wrong origin** — `:3000`, while the frontend serves on `:5173`.
2. **Stray path segment** — `rsplit('/', 1)[0]` strips only `callback`, leaving
   `/auth` in the URL.
3. **Wrong route** — the React route is `/invite`; `/invitations/accept` is the
   *API* path, not a page.

**Root cause, and the reason this matters beyond one link:** there is **no
`FRONTEND_BASE_URL` setting anywhere in the configuration**. The only setting
that happens to contain the frontend origin is an OAuth callback URL, so it was
string-hacked into service. Any future email needing a frontend link will
reach for the same broken lever.

Mitigating: `AcceptInvitePage` offers a manual token-paste fallback, so a
determined user who reads the dead URL can still extract the token. That is a
recovery path, not a working feature.

Combined with D-1, **member invitation — a core multi-user SaaS flow — does not
work end to end**: the email often is not sent, and when it is, the link 404s.

**Fix:** add `FRONTEND_BASE_URL` to settings, use it here, and add a test that
asserts the generated URL matches the declared frontend route. Password reset
returns its token to the caller rather than building a URL, so it is unaffected
— this is the only email that constructs a link.

## D-3 — HIGH: the tenant audit log is never written

`apps/common/audit.py` defines an `AuditLog` model, tenant-scoped, protected by
an append-only database trigger. The infrastructure is real and carefully built.

**It has zero write sites.**

```
AuditLog.objects.create   →  0 occurrences
```

The only hit anywhere is `PlatformAuditLog.objects.create` — the *operator*
trail, which is fully wired. Across 68 `@transaction.atomic` service functions
covering finance, debt, goals, budgeting, investments and tenancy — creating
accounts, deleting transactions, changing debt terms, closing a workspace —
none records anything. No tenant-facing endpoint exposes the model either, so
even a populated table would be unreadable.

The product principle is *"Implement complete audit trails for financial
actions."* It is met for platform staff and not for customers.

This matters most for the product's own use case. LedgerFlow is sold for
**households and families** — shared workspaces with multiple members and a
role hierarchy. If one member deletes an account or reclassifies a year of
transactions, there is no record of who did it. For a shared financial
workspace that is the question people most want answered.

What *is* tracked, to be precise:

| Trail | Status |
|---|---|
| Authentication (`LoginEvent`) | Written, working |
| Platform staff actions (`PlatformAuditLog`) | Written, working, immutable |
| Tenant business actions (`AuditLog`) | **Model + trigger only; nothing writes** |

**Fix:** this is a day of work, not a redesign. `apps/platform_admin/audit.py`
is a working reference implementation — `record()` plus a `diff()` helper
producing `{field: [before, after]}`. Port it to `common/audit.py`, call it
from the ~15 destructive tenant services first (delete/void/close/role change),
and expose a read endpoint.

## D-4 — MEDIUM: lost updates in the learning store

`apps/intelligence/automation_services.py:135`:

```python
profile, _ = MerchantProfile.objects.get_or_create(key=key, …)
profile.transaction_count += 1
profile.total_amount_minor += abs(txn.amount_minor)
…
counts = dict(profile.category_counts or {})
counts[category_id] = counts.get(category_id, 0) + 1
profile.category_counts = counts
```

Read-modify-write with no `select_for_update()` and no `F()` expression.
`get_or_create` itself is safe — `key` carries a unique constraint — but the
mutations that follow are not.

Two concurrent calls both read `transaction_count = 5` and both write `6`; one
increment is lost. The `category_counts` JSON is worse: it is read into a Python
dict, mutated, and written back wholesale, so a concurrent update loses an
entire **key**, not just a count.

Reachable concurrently: `bulk_decide` loops over suggestions calling
`learn_from_transaction` per row, and the same path runs from `quick_add` and
receipt processing.

**Impact:** silent degradation of auto-categorisation accuracy. It corrupts
predictions, not money — but it is invisible, and the store is precisely the
thing users cannot inspect to notice.

**Fix:** `select_for_update()` on the profile, or `F()` for the scalars plus a
JSONB atomic update for the counts.

## D-5 — MEDIUM: plan limits are check-then-act

Three sites — `tenancy/services.py:178`, `:281`, `finance/services.py:97` —
follow the shape:

```python
pending = Invitation.objects.filter(…).count()
ensure_can_add_member(current_count=Membership.objects.count() + pending)
```

Count, then decide, with no lock and no constraint backing the limit. Two
concurrent invitations both read the pre-change count, both pass, both commit.
A workspace on a 3-seat plan lands 4 members.

Severity is commercial rather than corrupting — a customer gets one seat they
did not buy — but it is a revenue leak that scales with concurrency, and it is
exploitable deliberately by anyone who notices.

**Fix:** take a row lock on the tenant (or subscription) row before counting, so
concurrent seat changes serialise.

## D-6 — LOW: balance drift is detected but not surfaced

`finance.reconcile_balances_for_tenant` recomputes each materialized
`AccountBalance` from immutable ledger lines, repairs drift, and logs at
`ERROR`. That is the right design — it repairs *and* complains, rather than
silently healing and hiding the bug that caused it.

But it stops at the log. Drift never raises a `PlatformNotification`, so it does
not appear on the operator console's "Needs attention" strip. Detected
divergence in a customer's money depends entirely on someone watching a log
stream.

**Fix:** call `raise_platform_alert(category="ledger.drift", severity="critical", …)`
alongside the log. The helper exists and is used elsewhere.

---

## What I got wrong while auditing

Recorded because the corrections are part of the evidence:

- I hypothesised the ledger lacked a database-level balance guarantee. Reading
  the posting service showed a full set of protections (§7). The hypothesis was
  wrong.
- A detector reported "0 of 68 service functions write an audit row" — the
  pattern was wrong for the codebase. Chasing it down produced the *correct and
  stronger* result: the write count is genuinely zero, but I would not have
  been entitled to claim it from the first grep.
- A second detector reported "no skip-to-content link" and "`LoginEvent` has no
  writers"; both were false. The customer shell has a skip link, and
  `LoginEvent` is written from `users/services/audit.py`.
- `debt/payoff.py` was flagged for unguarded `+=` on financial counters. Those
  are `@dataclass(slots=True)` in-memory projections — a false positive that
  incidentally **confirms** the "no persisted projections" rule holds.

Three of five leads were detector artifacts. A finding is not a finding until
the executing code path has been read.

---

## What is genuinely strong

Not filler — these determine how much the fixes above cost.

**The ledger posting path (`apps/ledger/services.py`) is textbook.** In one
function it does all of:

- `select_for_update()` on every affected account, serialising concurrent posts
- asserts debits equal credits and are non-zero before writing anything
- rejects mixed-currency entries at the entry level
- handles the idempotency-key race by catching `IntegrityError` and **returning
  the winner** rather than failing the caller
- updates balances with `F("balance_minor") + delta` — never read-modify-write
- does all of it inside a single transaction, with the outbox event included

That last point matters: the idempotency handling is the difference between a
retried payment webhook being safe and being a double charge.

**Integrity is enforced by the database where it counts.** 76 unique
constraints, 54 check constraints, and append-only triggers on both the ledger
and the platform audit log — the two tables where application-level discipline
would be insufficient because the people most able to tamper are the people
with database access.

**Duplicate-data risk is managed rather than assumed away.** `AccountBalance`
is an explicit materialisation of `SUM(LedgerLine)`, updated atomically under
lock, with a scheduled reconciler that recomputes from the immutable source. D-6
is a notification gap on top of a correct mechanism, not a missing mechanism.

**Soft-delete and uniqueness interact correctly** — unique constraints are
scoped to live rows throughout, so delete-then-recreate behaves.

---

## Correction found while fixing

**My D-3 recommendation to add RLS to `common_auditlog` would have broken the
product.** While wiring the audit writes I drafted a row-level-security
migration for that table, then found the exclusion documented in
`ledger/migrations/0002_financial_integrity.py`: the table is written during
workspace creation and invitation acceptance — operations that run *before* a
per-request tenant GUC exists — and read cross-tenant by trusted workers. The
policy would have rejected exactly the writes it most needed to capture.

Reverted. The constraint is now recorded in `record()`'s docstring instead,
with an explicit note that **any endpoint exposing these rows must filter on
`tenant_id` itself**. No such endpoint exists yet. The original design was
right and the audit was wrong to imply otherwise.

## Recommended order

1. **D-1 + D-2 together** — invitation flow is broken end to end; both are small
   and share a test. Add `FRONTEND_BASE_URL` while there.
2. **D-3** — tenant audit trail. Largest item; port the working platform
   implementation and start with destructive operations.
3. **D-4, D-5** — locking. A few lines each.
4. **D-6** — one call to an existing helper.

Items 1, 3 and 4 are hours. Item 2 is a day. None require architectural change,
which is the most useful thing this audit can tell you.
