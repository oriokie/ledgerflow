# `ledger` — The Double-Entry Accounting Core

The immutable, append-only accounting primitive everything financial is built
on. Small, deliberately boring, and the one place in the system where
correctness bugs would be catastrophic — so it does less, and is guarded more,
than any other module.

## Domain model

| Model | Purpose | Key fields |
|---|---|---|
| `Account` | An accounting primitive — not a bank account (see `finance.FinancialAccount` for that) | `kind` (`AccountKind`), `currency`, `is_system` |
| `JournalEntry` | A balanced set of lines posted atomically | `occurred_at`, `currency`, `memo`, `idempotency_key` (unique per tenant), `reverses` (self-FK, set on correction entries) |
| `LedgerLine` | One debit or credit within an entry | `entry`, `account`, `direction` (`Direction`), `amount_minor` (always positive; sign comes from `direction` + the account's normal-balance side) |
| `AccountBalance` | Materialized running balance per account, updated in the same transaction as every posting | `balance_minor`, `currency` |

`AccountKind`: `asset`, `liability`, `equity`, `income`, `expense`.
`NORMAL_DEBIT = {ASSET, EXPENSE}` — these increase on a debit; liability/
equity/income increase on a credit. `Account.normal_debit` is the property
consumers use rather than re-deriving this.

**Immutability**: `JournalEntry` and `LedgerLine` inherit `TenantOwnedModel`
directly (not `SoftDeletableModel`) and are protected by a database trigger
(`ledgerflow_forbid_mutation()`, in `apps/ledger/migrations/0002_financial_integrity.py`)
that raises on any `UPDATE`/`DELETE`. This is enforced at the database level,
not just by convention — it holds even against a raw SQL bug or a
misbehaving admin script.

## Service layer (`services.py`)

**`post_journal_entry(occurred_at, lines, idempotency_key, memo, reverses)`
is the single choke point every money movement in the system funnels
through.** It:

1. Short-circuits on a replayed `idempotency_key` (returns the existing
   entry rather than double-posting) — checked both proactively and via a
   unique-constraint race fallback.
2. `select_for_update()`s every account referenced, serializing concurrent
   posts against the same accounts.
3. Requires all lines share one currency (`LedgerError` otherwise — this is
   the enforcement point for "no cross-currency postings without an explicit
   FX entry," see [`fx.md`](./fx.md)).
4. Requires debits == credits and non-zero (`UnbalancedEntryError` otherwise).
5. Creates the `JournalEntry` + `LedgerLine`s (bulk-created, with `tenant_id`
   stamped explicitly since `bulk_create` bypasses `save()`).
6. Updates every referenced `AccountBalance` in the same transaction
   (`_signed_delta` computes the effect based on the account's normal-balance
   side).
7. Writes an `OutboxEvent` (`ledger.journal_entry.posted`).

`reverse_journal_entry(entry, idempotency_key, memo)` — the *only* way to
correct a mistake: posts the mirror-image entry (every line's direction
flipped) with `reverses=entry` set, never mutates history.

`create_account(name, kind, currency)` — provisions an `Account` +
zero-balance `AccountBalance` together, atomically, so an `Account` never
exists without somewhere to materialize a balance.

## Selectors (`selectors.py`)

`list_accounts(include_system)` — `select_related("balance")` so listing N
accounts with their balances is 1 extra query, not N. `account_balance(account)`
reads the materialized value (no aggregation over lines). `recompute_balance_minor(account)`
— the reconciliation path: sums every `LedgerLine` from scratch as the
source-of-truth check against the materialized value (used by
`finance.tasks.reconcile_balances_for_tenant`). `list_entries(limit, offset)`
— `prefetch_related` for lines + their accounts, ~3 queries regardless of N.

## Key workflow: posting an entry

```python
from apps.ledger.services import post_journal_entry, LineInput
from apps.ledger.models import Direction

entry = post_journal_entry(
    occurred_at=timezone.now(),
    idempotency_key="expense:...",     # caller-supplied; a retry with the same
                                        # key returns the same entry, never a duplicate
    lines=[
        LineInput(account_id=checking_ledger_account_id, direction=Direction.CREDIT, amount_minor=4200),
        LineInput(account_id=groceries_ledger_account_id, direction=Direction.DEBIT, amount_minor=4200),
    ],
)
```

In practice, almost nothing calls this directly — `apps.finance.services`
(`record_expense`, `record_income`, `record_transfer`, `void_transaction`) is
the intended caller, translating a user-facing single-entry mental model
("I spent $42 on groceries") into the correct two-line balanced entry. See
[`finance.md`](./finance.md) for how the sign/direction math works out for
both asset and liability accounts.

## API

Base path `/api/v1/ledger/`. Thin — most consumers should use `finance`'s
richer endpoints instead; this is exposed mainly for direct ledger inspection
and tooling.

| Method | Path | Purpose | Role required |
|---|---|---|---|
| `GET` | `/accounts/` | List ledger accounts | member (any) |
| `POST` | `/accounts/` | Create a ledger account directly | `MEMBER` |
| `GET` | `/entries/` | List journal entries | member (any) |
| `POST` | `/entries/` | Post a journal entry directly | `MEMBER` |

## Permissions

Standard `TenantScopedAPIView` + `IsTenantMember`; `required_role = Role.MEMBER`
on both view sets (writing to the ledger, even indirectly, needs at least
MEMBER — VIEWER is read-only everywhere).

## Extension points

`ledger` itself has almost no extension points by design — it's meant to stay
small and stable. The extension points that matter live one layer up: new
account *types* are a `finance` concern (see
[`finance.md`](./finance.md#extension-points)), and cross-currency posting is
a documented `fx` seam (see [`fx.md`](./fx.md) and
[`../EXTENSION_POINTS.md#cross-currency-support-documented-not-yet-built`](../EXTENSION_POINTS.md#cross-currency-support-documented-not-yet-built)).

## Testing

`tests/test_ledger.py` — balanced-entry enforcement, idempotency replay
(including the race-condition fallback path), currency-mismatch rejection,
reversal correctness, immutability trigger (`UPDATE`/`DELETE` raise at the DB
level). `tests/test_finance_engine.py` exercises the ledger indirectly
through `finance` services, which is where most of the "does the accounting
actually balance" coverage lives in practice.
