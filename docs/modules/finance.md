# `finance` — The User-Facing Domain Layer

Everything a user directly interacts with: accounts they hold, categories
they spend against, the transactions themselves, transfers, recurring
schedules, tags, payees, and receipt attachments. Sits directly on top of
`ledger` — every mutation here ultimately calls `ledger.services.post_journal_entry`.

## Domain model

| Model | Purpose | Key fields |
|---|---|---|
| `Institution` | Bank/aggregator reference data — **shared across tenants, not RLS-protected** | `name`, `country`, `aggregator`, `external_id` |
| `Wallet` | A named grouping of `FinancialAccount`s (e.g. a multi-currency "pot"). Never posts to the ledger itself — pure presentation/grouping layer | `name`, `is_default` |
| `FinancialAccount` | A real-world account the user holds | `account_type` (`AccountType`), `currency`, `ledger_account` (1:1 to `ledger.Account`), `wallet`, `institution`, `mask`, `metadata` (JSON) |
| `Category` | Hierarchical taxonomy (materialized path: `path`/`depth`, e.g. `"food.groceries"`) | `kind` (`CategoryKind`), `slug` (unique per tenant, stable machine reference for automation rules), `parent`, `ledger_account` (1:1, income/expense only — transfer categories have none) |
| `Payee` | A merchant, looked up by `normalized_name` (lowercased, whitespace-collapsed) so name variants merge | `default_category` |
| `Tag` | Free-form labels | — |
| `Transaction` | The domain aggregate a user edits | `amount_minor` (**signed**: negative = money out), `status` (`TransactionStatus`), `source` (`TransactionSource`), `category`, `payee`, `counter_account` (set for transfers), `transfer_group` (UUID pairing a transfer's two halves), `needs_review`/`review_reason`, `journal_entry` (FK, not 1:1 — a transfer's one entry backs two transactions) |
| `TransactionTag` | M2M through-table | unique on `(transaction, tag)` among live rows |
| `Attachment` | A receipt/document, stored in object storage | `storage_key`, `status` (`AttachmentStatus`), `checksum` |
| `RecurringTransaction` | A schedule template; never touches the ledger itself — only the transactions it materializes do | `txn_type`, `frequency`/`interval`/`starts_on`/`ends_on`/`max_occurrences`, `next_run_on`, `occurrences_created` |

`AccountType`: `checking`, `savings`, `credit_card`, `loan`, `cash`,
`investment`, `other`. `CategoryKind`: `income`, `expense`, `transfer`.
`TransactionStatus`: `pending`, `posted`, `reconciled`, `void`.
`TransactionSource`: `manual`, `imported`, `rule`, `recurring`.

**Indexes worth knowing about** (`Transaction.Meta.indexes`):
`txn_list_cursor_idx` (`tenant_id, -occurred_at, -id`) matches the global
list's cursor-pagination sort exactly, so listing is a constant-cost index
scan regardless of tenant size, not a top-N sort over the whole table.
`txn_non_transfer_idx` (partial, `transfer_group IS NULL`) serves every
report query (cash flow, category breakdown), which always excludes
transfers. `txn_needs_review` (partial, `needs_review=True`) backs the review
queue. See `PERFORMANCE.md` for the measured impact.

## Service layer (`services.py`)

The rule that makes it hang together: **a `FinancialAccount` and an
income/expense `Category` each own a backing `ledger.Account`.** Recording an
expense is uniformly "credit the account's ledger account, debit the
category's ledger account" — the ledger's normal-balance rules make the signs
work out whether the account is an asset (cash decreases) or liability (debt
increases).

| Function | Does |
|---|---|
| `create_financial_account(name, account_type, currency, ...)` | Provisions the backing `ledger.Account` + `FinancialAccount` together |
| `create_category(name, kind, currency, parent, slug, ...)` | Provisions a backing `ledger.Account` for income/expense kinds (none for transfer); computes materialized `path`/`depth`; `slug` defaults to a slugified name, unique per tenant |
| `record_expense(financial_account, category, amount_minor, occurred_at, ...)` | Posts a 2-line entry (credit account, debit category); creates a `Transaction` with negative `amount_minor`. Requires `category.kind == EXPENSE`, `amount_minor > 0` (sign is applied by the engine, not the caller) |
| `record_income(...)` | Mirror of `record_expense` — debit account, credit category; positive `amount_minor` |
| `record_transfer(from_account, to_account, amount_minor, ...)` | Posts **one** balanced entry (credit source, debit destination, no category account) and creates **two** linked `Transaction`s sharing a `transfer_group`. Net worth is unchanged; reports exclude anything with a `transfer_group` |
| `void_transaction(txn, idempotency_key, memo)` | Posts the reversing entry via `ledger.reverse_journal_entry` and marks the transaction(s) `VOID` — handles both halves of a transfer off the one shared entry |
| `update_transaction(txn, category, payee, memo)` | Edits only what does **not** affect the ledger (category/payee/memo). Amount/account/direction are immutable — changing what actually happened requires void + repost. Uses a sentinel default so `category=None` means "clear it" while omitting the arg means "leave it alone" |
| `flag_transaction_for_review(txn, reason)` | Sets `needs_review`/`review_reason` — a real, queryable state (surfaced by the partial index), used by automation's `flag_review` action and manual review requests |
| `recompute_account_balance(financial_account)` | Reconciliation helper: recomputes the materialized balance from immutable ledger lines and writes it back |

Also: `tagging.py` (`set_transaction_tags` — set-based diff, not append-only),
`payees.py` (`create_payee`, `get_or_create_payee` — the idempotent variant
for import pipelines), `wallets.py` (`create_wallet`, `assign_account_to_wallet`),
`attachments.py` (`request_attachment_upload` → presigned URL,
`confirm_attachment_upload`), `recurring.py` (see below).

## Selectors (`selectors.py`)

All single-query or small-fixed-query-count aggregates over the materialized
`AccountBalance` / grouped `Transaction` sums — never a Python loop over the
full transaction history:

| Function | Returns |
|---|---|
| `net_worth()` | Per-currency `[NetWorth(assets, liabilities)]` — one grouped aggregate over `AccountBalance` |
| `cash_flow(start, end)` | Per-currency `[CashFlow(income, expense)]` over `[start, end)`, transfers excluded |
| `category_breakdown(start, end, expense=True)` | Spend (or income) grouped by category, biggest first |
| `account_statement(financial_account, start, end)` | `(opening_balance, [(txn, running_balance), ...])` via a SQL window function — no per-row queries |
| `list_transactions(financial_account=None)` | Ordered, **unsliced** queryset for cursor pagination; no `select_related` (the list serializer reads only `*_id` fields) |
| `account_current_balance_minor(financial_account)` | Single materialized-balance read |
| `wallet_balances(wallet)` | Per-currency sum across the wallet's member accounts — never summed cross-currency |

## Recurring transactions (`recurring.py`, `schedule.py`, `tasks.py`)

`create_recurring_transaction(...)` defines a template; nothing posts yet.
A daily Celery beat task materializes due occurrences — see
[`../DEPLOYMENT.md#celery-beat-schedule`](../DEPLOYMENT.md#celery-beat-schedule)
for the fan-out topology (`dispatch_recurring_transactions` →
`dispatch_recurring_batch` → `run_recurring_for_tenant`, streamed and batched
so no single beat tick loads every tenant into memory or enqueues an
unbounded number of tasks).

`nth_occurrence()` (`schedule.py`) always computes from the **original anchor
date** (`starts_on + n periods`), never by repeatedly incrementing the
previous date — this preserves the anchor day across month-length
differences (a "31st of the month" schedule lands on Feb 28/29, then back to
Mar 31, not drifting to the 28th forever).

`run_due_template(rec, today)` locks the template row (`select_for_update`)
and walks forward one period at a time until caught up, so a template that
fell behind (e.g. the worker was down) posts every missed occurrence in one
run. Each posting's idempotency key is `recurring:{template_id}:{date}`, so
re-running is always safe.

`reconcile_balances_for_tenant` (weekly beat) recomputes every account's
balance from the ledger and logs any drift — the materialized balance is a
cache of the immutable ledger, and caches drift.

## Signals (`signals.py`)

`post_save` on `Transaction`/`AccountBalance` → `apps.common.cache.invalidate_tenant`
via `transaction.on_commit` (so a rolled-back write never invalidates).
Hooking the models rather than each service means a new write path can't
forget to invalidate the derived-analytics cache.

## API

Base path `/api/v1/finance/`.

| Method | Path | Purpose | Role |
|---|---|---|---|
| `GET`/`POST` | `/accounts/` | List / create financial accounts | VIEWER / MEMBER |
| `GET` | `/accounts/<id>/statement/` | Statement with running balance | VIEWER |
| `GET`/`POST` | `/wallets/` | List / create wallets | VIEWER / MEMBER |
| `GET` | `/wallets/<id>/` | Wallet balance (per-currency) | VIEWER |
| `POST` | `/wallets/assign-account/` | Assign/unassign an account to a wallet | MEMBER |
| `GET`/`POST` | `/categories/` | List / create categories | VIEWER / MEMBER |
| `GET`/`POST` | `/payees/` | List / create payees | VIEWER / MEMBER |
| `GET`/`POST` | `/tags/` | List / create tags | VIEWER / MEMBER |
| `GET`/`POST` | `/transactions/` | Cursor-paginated list / record expense or income | VIEWER / MEMBER |
| `GET`/`PATCH` | `/transactions/<id>/` | Read / edit category-payee-memo | VIEWER / MEMBER |
| `POST` | `/transactions/<id>/void/` | Void via reversing entry | MEMBER |
| `PUT` | `/transactions/<id>/tags/` | Replace a transaction's tag set | MEMBER |
| `GET` | `/transactions/<id>/attachments/` | List attachments | VIEWER |
| `POST` | `/transactions/<id>/attachments/request-upload/` | Get a presigned upload URL | MEMBER |
| `POST` | `/attachments/<id>/confirm/` | Confirm an upload completed | MEMBER |
| `POST` | `/transfers/` | Move money between two owned accounts | MEMBER |
| `GET`/`POST` | `/recurring/` | List / create recurring templates | VIEWER / MEMBER |
| `GET` | `/net-worth/` | Per-currency assets/liabilities/net | VIEWER |
| `GET` | `/cash-flow/` | Per-currency income/expense over a range | VIEWER |
| `GET` | `/category-breakdown/` | Spend by category over a range | VIEWER |

List endpoints use `TransactionCursorPagination` (`ordering = (-occurred_at, -id)`)
— see [`../ARCHITECTURE.md#performance-posture`](../ARCHITECTURE.md#performance-posture).

## Permissions

Standard `TenantScopedAPIView` + `IsTenantMember`. Most views use
`WriteRequiresMemberMixin` (VIEWER for GET, MEMBER for anything mutating);
statement/net-worth/cash-flow/category-breakdown are `required_role = Role.VIEWER`
outright since they're pure reads with no write branch.

## Extension points

- **New account types**: add to `AccountType`, classify in `_ASSET_TYPES`/
  `_LIABILITY_TYPES` in `services.py` — see
  [`../EXTENSION_POINTS.md`](../EXTENSION_POINTS.md#adding-a-new-financial-account-type).
- **Cross-currency transfers**: currently rejected (`CurrencyMismatchError`)
  — documented seam via `apps.fx`, see [`fx.md`](./fx.md).
- **Bank-import / pending→posted reconciliation pipeline**: `TransactionStatus.PENDING`
  and `external_id` (idempotent-import unique constraint) already exist for
  this; the import pipeline itself is a documented next major build, not yet
  implemented.

## Testing

`tests/test_finance_engine.py` (core posting correctness — balanced entries,
signs, transfers, void, currency mismatches), `tests/test_finance_modules.py`
(tagging, payees, wallets, attachments, recurring date math),
`tests/test_finance_api.py` / `tests/test_finance_modules_api.py` (HTTP layer),
`tests/test_recurring.py` (materialization, idempotent replay, tenant
fan-out — see [`../TESTING.md`](../TESTING.md#testing-background-tasks) for
the transactional-test pattern this requires), `tests/test_caching.py`
(write-triggers-invalidation via the signals above).
