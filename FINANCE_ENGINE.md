# LedgerFlow — Core financial engine

How accounts, categories, transactions, transfers, balances, recurring
schedules, budgets, and financial calculations interact. Everything here runs
against real PostgreSQL 16 + Redis 7 — see "Verification".

Design priorities, in order: **accuracy → auditability → extensibility →
performance.** Where they conflict, the earlier one wins (e.g. we refuse to
silently sum mixed currencies even though it would be "simpler").

## The one idea that ties it together

Personal-finance users think in **single entry**: "I spent $50 on
groceries." Accounting truth is **double entry**: every debit has an equal
credit. The engine bridges the two with a single rule:

> **Every `FinancialAccount` and every `Category` owns a backing
> `ledger.Account`.**

- FinancialAccounts → an **asset** ledger account (checking, savings, cash,
  investment) or a **liability** one (credit card, loan).
- Income/expense Categories → an **income**/**expense** ledger account.

With that, "spend $50 on groceries from checking" becomes a balanced entry
mechanically:

```
CREDIT  checking (asset)     50      # money leaves the account
DEBIT   groceries (expense)  50      # expense grows
```

and the same operation on a credit card is *identical in code* —
`CREDIT the account's ledger account, DEBIT the category's` — because the
ledger's normal-balance rules make a credit **decrease** an asset but
**increase** a liability. One uniform posting path, correct for every account
type. Nothing posts to the ledger except through
`ledger.services.post_journal_entry`, the single choke point that enforces
balance, single-currency, and idempotency.

## Two layers, on purpose

| Layer | Model | Nature |
|---|---|---|
| Domain / UX | `finance.Transaction` | mutable-ish (status transitions), user-facing, signed amount, category, payee, tags |
| Accounting truth | `ledger.JournalEntry` + `LedgerLine` | **immutable, append-only** (DB trigger blocks UPDATE/DELETE), balanced |

A `Transaction` links to the `JournalEntry` it produced. Corrections never
mutate history — they post a **reversing entry**. This is what makes the
system auditable: the ledger is a complete, tamper-evident record, and the
materialized balances can always be recomputed from it
(`recompute_account_balance` does exactly that, for reconciliation).

## Transactions: income & expense

`record_expense` / `record_income` (in `finance/services.py`) each:
1. post one balanced journal entry (uniform direction rules above),
2. create a `Transaction` with a **signed** `amount_minor` — negative = money
   out, positive = money in, from the user's cash-flow perspective,
3. mark it `POSTED` and stamp `posted_at`.

The signed convention means a statement or cash-flow total is a plain `SUM`,
never a per-row branch. Amounts are always integer **minor units** (cents) —
never floats — via the `Money` value object.

## Transfers: first-class, never double-counted

Moving your own money between accounts is **neither income nor expense** — net
worth must not change, and it must never inflate spending. The subtle part is
the domain representation. `record_transfer`:

- posts **one** balanced journal entry — `CREDIT source, DEBIT destination`,
  touching **no** category account (so it can't appear in any income/expense
  report), and
- surfaces as **two linked `Transaction` rows** (one per account, opposite
  signs) sharing that single entry (`journal_entry` is a FK, not a
  OneToOne, precisely to allow this) and a common `transfer_group` UUID.

Why two rows: each account's statement is then a clean
`WHERE financial_account = X` with naturally-correct signs, and net worth nets
to zero across the two automatically. Every report that must exclude transfers
does so with one predicate: `transfer_group IS NULL`. Verified:
`test_transfer_is_not_income_or_expense_and_nets_to_zero`.

Cross-currency transfers are **rejected** with a clear error rather than
silently mishandled — a correct multi-currency transfer needs an FX bridge
entry (the `fx.ExchangeRate` model is the seam), which is a documented
extension, not a shortcut taken here.

## Balances

- **Current balance** is materialized in `ledger.AccountBalance`, updated
  inside the same transaction as every posting via an atomic `F()` increment.
  Reads are O(number of accounts), not O(number of transactions) — net worth
  over a million transactions is still a handful of rows.
- **Net worth** = Σ asset balances − Σ liability balances, **per currency**.
  Mixed-currency consolidation is intentionally left to an FX layer; summing
  them blind would be a correctness bug.
- **Statement running balance** reflects the account's *true* balance after
  each row. For a liability account this correctly shows the amount owed
  growing on a purchase — handled by a per-account sign
  (`+1` asset / `−1` liability) applied to the windowed cumulative cash-flow.
  Computed with a SQL window function + two aggregates: no per-row queries.
  Verified for both asset and liability accounts.

## Voiding

`void_transaction` posts the reversing journal entry (restoring balances) and
flags the domain transaction(s) `VOID` — including both halves of a transfer
off their shared entry. History is preserved; reports filter `VOID` out.

## Recurring transactions

A `RecurringTransaction` is a **template**, not a posted transaction — it never
touches the ledger itself, so it can be edited or paused without rewriting
already-posted history. A daily Celery-beat task (`finance.tasks`) materializes
due templates into real transactions via the same `record_*` services.

Three properties that matter:
- **Idempotent** per (template, scheduled date): the derived journal-entry
  idempotency key (`recurring:{id}:{date}`) means re-running the scheduler, or
  catching up several missed days at once, never double-posts.
- **Catch-up**: if the worker was down, one run walks forward period-by-period
  posting every missed occurrence, then advances. Verified:
  `test_catch_up_posts_all_missed_occurrences`.
- **Anchor-preserving schedules**: occurrences are computed as
  `starts_on + n·interval` from the original anchor (via `relativedelta`),
  never by incrementing the previous date — so a "31st of the month" schedule
  yields Jan 31 → Feb 28 → **Mar 31**, not drifting to the 28th forever.
  Verified: `test_monthly_anchor_is_preserved_across_short_months`.

Because `RecurringTransaction` is RLS-protected, the beat task iterates active
tenants (from the non-RLS `tenancy_tenant` control-plane table), binds each
tenant's RLS GUC + contextvar exactly like a request, and processes each in
its own transaction so one tenant's failure can't roll back another's. Proven
end-to-end through a real Celery worker + Redis broker.

## Budgets

Budgets are a **read-only overlay** — they never touch the ledger. A `Budget`
has a period (weekly/monthly/quarterly/yearly) anchored at `starts_on`; each
`BudgetLine` caps spending in one expense category.

`budget_status` computes, per line for the period containing a given date:
- **actual** = spend across the category's **entire subtree**, matched with a
  single materialized-path range (`path LIKE 'food.%'`) — no recursive CTE, so
  spending on a child category rolls up to a parent's budget. Verified:
  `test_budget_subtree_spending_rolls_up_to_parent`.
- **effective limit** = limit + single-period **rollover** carry (previous
  period's unspent, if the line rolls over). Deeper multi-period carry is a
  bounded, documented extension.
- remaining, percent used, and an `over_budget` flag.

Period alignment is pure date math (`period_bounds`) that finds the window
containing the as-of date without walking the whole history.

## Financial calculations (read projections)

All in `finance/selectors.py`, all database aggregates (no N+1):
- `net_worth()` — per-currency assets/liabilities/net from materialized
  balances.
- `cash_flow(start, end)` — income vs expense vs net, **transfers excluded**.
- `category_breakdown(start, end)` — spend (or income) grouped by category,
  transfers excluded, biggest first.
- `account_statement(account, start, end)` — ordered rows with running
  balance (window function).

## How the pieces interact (one worked example)

```
create_financial_account("Checking", checking)   -> asset ledger acct + balance row
create_financial_account("Visa", credit_card)     -> liability ledger acct
create_category("Groceries", expense)              -> expense ledger acct
record_income(Checking, Salary, 300000)            -> balanced entry; Checking +300000; cash-flow income +3000.00
record_expense(Checking, Groceries, 5000)          -> Checking -5000; expense report +50.00
record_transfer(Checking -> Savings, 40000)        -> Checking -40000, Savings +40000; net worth unchanged; excluded from cash flow
RecurringTransaction(expense, Rent, monthly)       -> beat task posts one record_expense each month, idempotently
Budget(monthly) + line(Groceries, 50000)           -> budget_status: actual 5000 / limit 50000, 10% used
net_worth()                                         -> Σ assets − Σ liabilities, per currency
```

## API surface (`/api/v1/`)

`finance/accounts/`, `.../accounts/{id}/statement/`, `finance/categories/`,
`finance/transactions/` (+ `.../{id}/void/`), `finance/transfers/`,
`finance/recurring/`, `finance/net-worth/`, `finance/cash-flow/`,
`finance/category-breakdown/`; `budgeting/budgets/`, `.../{id}/lines/`,
`.../{id}/status/`. All tenant-scoped (RLS-bound at the DRF layer), reads need
VIEWER, writes need MEMBER — enforced by a method-aware role mixin and
verified (`test_viewer_can_read_but_not_write`).

## Verification

Against real PostgreSQL 16 + Redis 7:
- **135 tests pass** (90% coverage), stable across three consecutive runs.
  New this build: 16 core-engine + 11 recurring + 9 budget + 6 API = 42.
- Double-entry balance, credit-card liability semantics, transfer net-zero +
  report exclusion, void reversal, asset & liability statement running
  balances, idempotency, currency-mismatch rejection, and **tenant isolation
  via RLS** all asserted against both the domain row and the ledger it wrote.
- The recurring beat task materialized due occurrences **through a real
  Celery worker + Redis broker**, correctly RLS-scoped per tenant.
- `ruff` + `black`: clean. `manage.py check --deploy`: zero issues. No
  migration drift.

## Wallets

A `Wallet` groups one or more `FinancialAccount`s under a name (e.g. "Travel
Fund" holding a USD and a EUR account together). It is deliberately **not** a
new accounting primitive — it never posts anything itself and owns no ledger
account. Each member account keeps posting to its own ledger account exactly
as before; `wallet_balances()` sums the members' materialized balances
**per currency** (same no-blind-cross-currency-sum discipline as
`net_worth()`). An account belongs to at most one wallet (`wallet` is a
nullable FK on `FinancialAccount`, not a through table) — moving an account
between wallets, or out of any wallet, is one `assign_account_to_wallet` call.

## Payees

`Payee` lookups are keyed by a **normalized** name (whitespace-collapsed,
lowercased), enforced by a partial unique constraint — "Trader Joe's",
"trader joe's ", and "TRADER JOE'S" all resolve to the same record. This is
what makes payee-based reporting and default-category assignment useful
instead of fragmenting across near-duplicate free-text names. `get_or_create_payee`
is the idempotent variant for import pipelines, which will see the same
merchant name spelled inconsistently across statements.

## Tags

`set_transaction_tags` is **set-based**: it diffs the desired tag list
against the transaction's current tags and only writes what changed. Calling
it twice with the same list is a no-op. Building this surfaced a real
uniqueness bug in the original schema — `TransactionTag`'s unique constraint
wasn't scoped to live rows, so removing and re-adding the same tag to a
transaction would permanently collide with its own soft-deleted history.
Fixed to match every other soft-deletable uniqueness constraint in the app
(`condition=Q(deleted_at__isnull=True)`).

## Attachments

Receipts/documents use a **two-step presigned-upload lifecycle** — the app
server never proxies file bytes:
1. `request_attachment_upload` creates a `PENDING` `Attachment` row and
   returns a presigned S3 PUT URL (`apps/common/storage.py`, built on
   `django-storages`' `S3Boto3Storage`). The client uploads directly to the
   bucket.
2. `confirm_attachment_upload` flips it to `UPLOADED` once the client's
   upload succeeds. Idempotent — confirming twice is a no-op.

`generate_presigned_upload_url` degrades gracefully to `None` on a
non-S3 backend (local dev's `FileSystemStorage`) rather than raising, so
callers must handle the no-presign case explicitly. Verified with a fake
boto3-shaped client (no real AWS credentials exist in this environment) —
the actual S3 wiring is exercised for real once `AWS_STORAGE_BUCKET_NAME`
is set in production. A hard 25MB size cap is enforced server-side before
any URL is issued. Production hardening noted as a follow-up: verify the
actual uploaded object's size/ETag with a HEAD request before confirming,
rather than trusting the client-reported checksum.

## Transaction editing

`update_transaction` edits exactly the fields that do **not** affect the
ledger — category, payee, memo. Amount, account, and direction stay
immutable: changing what actually happened financially still requires
`void_transaction` + a fresh posting, never a mutation, so the ledger stays
the single source of truth for "what really moved." Validation:
- rejects editing a `VOID` transaction,
- rejects a category whose `kind` doesn't match the transaction's sign
  (an expense transaction needs an expense category), and
- rejects setting **any** category on a transfer leg (transfers must stay
  category-less — that's part of what keeps them excluded from every
  income/expense report via `transfer_group IS NULL`).

`category`/`payee` use a sentinel default rather than `None`, so
`category=None` means "clear it" while omitting the argument means "leave it
alone" — the same distinction the PATCH endpoint's serializer makes via
`required=False` vs. an explicit `null`.

## Pagination

The transaction list endpoint uses **cursor pagination**
(`apps.common.pagination.CursorPagination`), not offset/limit — offset
pagination degrades badly on a large, high-churn table (the database still
walks past every skipped row). Building this surfaced a real bug: the
underlying selector was pre-slicing with `[offset:offset+limit]`, which
DRF's cursor paginator cannot re-order — removed, since cursor pagination
was always the intended long-term strategy for this table (the module's own
docstring said so) and offset/limit was the exact anti-pattern it warns
against. Ordering is `(-occurred_at, -id)` — chronological by when the money
moved, with the UUIDv7 id as a required unique tiebreaker for cursor
stability, not the generic `-created_at` default (which would sort an
imported/backfilled transaction by insert time instead of transaction time).

## API surface additions (`/api/v1/finance/`)

`wallets/`, `wallets/{id}/`, `wallets/assign-account/`, `payees/`, `tags/`,
`transactions/{id}/` (GET + PATCH), `transactions/{id}/tags/` (PUT),
`transactions/{id}/attachments/` (GET), `.../attachments/request-upload/`
(POST), `attachments/{id}/confirm/` (POST). Same method-aware VIEWER/MEMBER
role enforcement as the rest of the finance API.

## Verification (this build)

- **174 tests pass** (91% coverage), stable across three consecutive runs.
  39 new: 25 service-layer (wallets, payees, tags, attachments, transaction
  editing) + 14 API-level (including pagination and role enforcement).
- **Four real bugs found by testing against real Postgres/RLS, not by
  inspection** — the part worth trusting most:
  1. `TransactionTag`'s unique constraint wasn't scoped to live rows —
     removing and re-adding a tag would permanently collide with its own
     soft-deleted history.
  2. `set_transaction_tags`' `bulk_create` bypassed the model's `save()`
     override that auto-stamps `tenant_id` — RLS correctly rejected the
     unstamped rows (`bulk_create` doesn't call `.save()` per instance; fixed
     by stamping `tenant_id` explicitly, matching the existing pattern in
     `ledger.services.post_journal_entry`'s own `bulk_create` call).
  3. `update_transaction` referenced `txn.transfer_group_id`, but
     `transfer_group` is a plain `UUIDField`, not a foreign key — no `_id`
     accessor exists.
  4. The transaction list selector's `[offset:offset+limit]` pre-slice broke
     DRF's cursor paginator, which needs to control ordering/limiting itself.
- `ruff`/`black`: clean. `manage.py check --deploy`: zero issues (including
  fixing two real OpenAPI operation-ID collisions from the new detail
  endpoints). No migration drift.

## Deliberately deferred (documented, not forgotten)

- **Cross-currency** transfers and multi-currency net-worth consolidation —
  the `fx.ExchangeRate` model is the seam; blind summing is refused today.
- **Multi-period budget rollover** (only single-period carry is computed).
- **Investment holdings / unrealized gains** — investment accounts hold a cash
  balance today; positions/lots are a future context depending inward on the
  ledger.
- **Scheduler at very large tenant counts** — the beat task scans active
  tenants; a dedicated BYPASSRLS reader role could fetch only *due* tenants in
  one query. Noted, not needed at current size.
- **Pending→posted reconciliation** for imported bank-feed transactions (the
  `PENDING` status and import idempotency key exist; the clearing flow is a
  bank-import pipeline, a natural next build).
- **Attachment upload verification** — confirmation currently trusts the
  client-reported checksum/size rather than a server-side HEAD request
  against the uploaded object; real AWS credentials don't exist in this
  environment to exercise that path.
