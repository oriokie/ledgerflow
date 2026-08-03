# LedgerFlow — database schema

20 domain tables across six bounded contexts, 15 under Row-Level Security.
Every table verified on PostgreSQL 16 (migrations, RLS, triggers, indexes).

## Bounded contexts & tables

```
common      OutboxEvent, AuditLog                         (cross-cutting)
tenancy     Tenant, Membership, UserProfile               (who + workspace)
fx          ExchangeRate                                  (global reference)
ledger      Account, JournalEntry, LedgerLine,            (immutable money truth)
            AccountBalance
finance     Institution, FinancialAccount, Category,      (user-facing domain)
            Payee, Tag, Transaction, TransactionTag,
            Attachment
budgeting   Budget, BudgetLine                            (read-side, on top)
```

## Relationship map

```
User ─1:1─ UserProfile
User ─M:N (Membership)─ Tenant                         (roles: owner/admin/member/viewer)

FinancialAccount ─1:1─ ledger.Account (asset|liability)
Category         ─1:1─ ledger.Account (income|expense)   (contra side of a spend)
Category         ─self─ parent                            (materialized path + depth)

Transaction ─N:1─ FinancialAccount
Transaction ─1:1─ ledger.JournalEntry (nullable: pending feed items post later)
Transaction ─N:1─ Payee / Category / counter_account
Transaction ─M:N (TransactionTag)─ Tag
Transaction ─1:N─ Attachment (blob in object storage; row holds key + checksum)

JournalEntry ─1:N─ LedgerLine ─N:1─ Account   (Σdebits == Σcredits, enforced in service)
Account      ─1:1─ AccountBalance (materialized, transactional)

Budget ─1:N─ BudgetLine ─N:1─ Category
```

## Financial-integrity rules (verified on Postgres)

| Rule | Mechanism | Verified |
|---|---|---|
| No cross-tenant reads | RLS `USING (tenant_id = current GUC)` on 15 tables | tenant B saw 0 of tenant A's rows |
| No cross-tenant writes | RLS `WITH CHECK` | smuggled insert rejected by policy |
| Fail-closed | `NULLIF(current_setting(...), '')` → no context = 0 rows | unset GUC returned 0 rows |
| Ledger is append-only | `BEFORE UPDATE OR DELETE` trigger raises | UPDATE + DELETE both blocked, row survived |
| Positive line amounts | `CHECK (amount_minor > 0)` | constraint present |
| Idempotent posting | `UNIQUE (tenant_id, idempotency_key)` | — |
| Idempotent import | partial `UNIQUE (financial_account, external_id) WHERE external_id<>''` | — |
| Balanced entries | service layer (`post_journal_entry`) | tested in ledger suite |

## Indexing strategy

- **BRIN** on `occurred_at` (transaction, journal_entry): tiny index, ideal for append-only time-series at scale.
- **GIN** on `metadata` JSONB (transaction, financial_account): query the extensibility hatch without new columns.
- **Partial** index on `status='pending'`: hot bank-feed reconciliation path stays small.
- **Composite** `(tenant_id, financial_account, -occurred_at)` for statements; `(tenant_id, category, -occurred_at)` for budgets.
- **Partial UNIQUE** with `WHERE deleted_at IS NULL`: soft-deleted rows don't block re-creating a name.

## Conventions

- **PKs**: UUIDv7 everywhere (`common/ids.py`) — time-ordered for index locality, non-enumerable for IDOR safety.
- **Money**: integer minor units + ISO-4217 currency; never float.
- **Audit fields**: `created_at`, `updated_at`, `created_by_id`, `updated_by_id` on every tenant row (auto-stamped from actor context).
- **Soft delete**: `deleted_at` / `deleted_by_id` on mutable/reference models; managers hide dead rows, `all_objects` includes them. Immutable ledger tables are exempt by design.

## Extensibility (no-redesign paths)

1. New attribute on a churny model → `metadata` JSONB, no migration; graduate to a typed column once queried heavily.
2. New context (e.g. `goals`, `investments`) → new app; depends inward on `ledger`/`tenancy`, adds its own RLS lines to the integrity migration.
3. Cross-currency entries → `fx.ExchangeRate` already timestamped/sourced; a two-legged entry links the rate used.
4. Scale-out → `transaction` / `ledger_line` convert to native RANGE(`occurred_at`) monthly partitions (ops-layer DDL; unique keys already include tenant/account).

## Addendum: identity & auth foundation tables

Added when building the authentication/SaaS foundation (see `AUTH.md` for
full design rationale). None of these are RLS-protected — they belong to a
`User` (global, not per-tenant) or are tenancy control-plane data following
the same reasoning as `Membership`/`Tenant`.

```
users_user               custom user (email login, Argon2 password hash)
users_userprofile        locale/timezone/currency/avatar/phone — moved here
                          from tenancy (identity concern, not a workspace one)
users_totpdevice         TOTP secret (Fernet-encrypted at rest), one per user
users_mfabackupcode      single-use backup codes (Argon2-hashed)
users_webauthncredential passkeys: credential_id, COSE public key, sign_count
users_socialaccount      OAuth-linked accounts (provider, provider_user_id)
users_loginevent         auth audit trail — every login attempt, any method

tenancy_tenant            + `type` column (personal/household/organization)
tenancy_invitation        hashed token, role ceiling enforced at creation,
                           expiry, status (pending/accepted/revoked)
```

`Invitation.token_hash` follows the same discipline as passwords and backup
codes: the raw token is shown to the caller exactly once, at creation, and
never stored.

## Addendum: financial-engine refinements

Added when building the core financial engine (see `FINANCE_ENGINE.md`).

- **`finance_transaction.journal_entry`**: changed from OneToOne to a **FK**
  (`related_name="transactions"`). One balanced `JournalEntry` can underlie a
  transfer that surfaces as two domain transactions (one per account);
  income/expense entries still back exactly one.
- **`finance_transaction.transfer_group`** (UUID, indexed, nullable): pairs the
  two halves of a transfer. `transfer_group IS NULL` is the single predicate
  every income/expense report uses to exclude transfers.
- **`finance_recurringtransaction`** (new, RLS-protected): a schedule template
  (txn_type, account(s), category/payee, positive amount, frequency/interval,
  starts_on/ends_on/max_occurrences) plus runtime state (next_run_on,
  occurrences_created, last_run_at, is_active). Indexed on
  `(tenant_id, is_active, next_run_on)` for the scheduler's due query. The
  template never touches the ledger; a daily Celery-beat task materializes due
  occurrences into real transactions idempotently.

## Addendum: wallets, payees/tags fix, attachment lifecycle

Added when closing out the financial engine's remaining gaps (see
`FINANCE_ENGINE.md`).

- **`finance_wallet`** (new, RLS-protected): a named grouping over
  `FinancialAccount`s (`FinancialAccount.wallet`, nullable FK). Owns no
  ledger account itself — balances are computed by summing members'
  materialized balances per currency at read time.
- **`finance_transactiontag`**: fixed its unique constraint to
  `condition=Q(deleted_at__isnull=True)`, matching every other
  soft-deletable uniqueness constraint in this app. Without the fix,
  removing and re-adding the same tag to a transaction permanently collided
  with its own soft-deleted history.
- **`finance_attachment.status`** (new field, PENDING/UPLOADED): supports the
  two-step presigned-upload lifecycle — a row exists before the file is
  actually in object storage, and is confirmed after.
