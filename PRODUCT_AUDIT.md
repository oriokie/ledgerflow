# LedgerFlow — Product & Domain Audit

A module-by-module review from product, engineering and financial-domain
perspectives, with the highest-severity gap implemented.

**Scope note, stated up front:** I audited the Accounts, Transactions, Ledger,
Categories, Budgets, Net Worth and Analytics modules against the running code
and test suite. Investments, Debt payoff, and the bank-format importers
(OFX/QFX/MT940/CAMT.053) I reviewed only at the model and route level, not in
depth. Where I have not verified something, it is marked **[unverified]** rather
than asserted.

---

## What the architecture gets right

Worth recording, because it constrains what should change.

The ledger core is genuinely well-built and the brief's instruction to assume
the architecture is correct is justified:

- Immutable, append-only journal with a **database trigger** blocking
  `UPDATE`/`DELETE` — not merely an application-layer convention. Corrections
  are reversing entries.
- `post_journal_entry` is a **single choke point** for all money movement,
  enforcing the double-entry invariant, one currency per entry, idempotency, and
  materialized balance updates inside one transaction with `SELECT FOR UPDATE`.
- Row-level security that **fails closed** — a query with no tenant bound
  returns zero rows, proven by a direct-DB test.
- Cross-currency consolidation deliberately refuses to silently sum mixed
  currencies, and reports `converted: false` when a rate is missing.

That last one is the mark of someone who has been burned by a finance app
confidently displaying a wrong number. It is the right instinct, and it is the
standard the rest of the product should be held to.

---

## 1. Launch Blockers

### 1.1 Opening balances — **IMPLEMENTED**

**The gap.** There was no way to record what an account already held. A user
with an existing bank account could not represent reality. Every competitor —
Monarch, Copilot, YNAB, Simplifi — makes this the first step of onboarding,
because without it every balance the product displays is wrong from day one.

Tellingly, `AccountKind.EQUITY` was defined in the model and **never
instantiated anywhere** — the accounting primitive this requires was present but
unused.

**Why it's a blocker rather than an enhancement.** It is unrecoverable. Every
balance, net-worth figure, budget calculation and reconciliation downstream
inherits the error, and a user who imports six months of history against a wrong
starting balance has six months of wrong running balances.

**What was implemented.**

Opening balances post a **real double-entry journal entry** against a system
`Opening Balance Equity` account — never a stored column:

| Account kind | Entry |
|---|---|
| Asset | DEBIT the account, CREDIT opening equity ("you have it") |
| Liability | CREDIT the account, DEBIT opening equity ("you owe it") |

Design decisions worth defending:

- **Callers pass a positive magnitude** in the account's natural direction, and
  the service derives debit/credit from the account type. Making callers reason
  about signs is precisely how sign-flip bugs reach production. The UI reinforces
  this by relabelling the field to "Amount owed today" for cards and loans.
- **Idempotent per account** (`opening:{account_id}`), so a retried request can
  never post twice.
- **Backdatable.** Users start tracking mid-month; the opening entry must sit
  before their earliest imported transaction or every running balance in the
  statement is wrong.
- **Equity is excluded from net worth.** It is the counterparty to the assets it
  funded, not a second asset — including it would double-count.

*Impact:* +7 model fields, 1 additive migration (zero-downtime, safe defaults),
3 new service functions, 3 API endpoints, 23 new tests.

### 1.2 Account lifecycle — **IMPLEMENTED**

Accounts had only `is_active`. There was no archiving, no hiding, and no way to
exclude an account from reporting.

Three concepts, kept deliberately **separate** because conflating them causes
real damage:

| Concept | Field | Meaning |
|---|---|---|
| Lifecycle | `archived_at` | Closed. Leaves pickers and net worth; keeps all history. |
| Presentation | `is_hidden` | Collapsed out of the UI. **Still counts in every total.** |
| Reporting | `include_in_net_worth`, `include_in_budgets` | Arithmetic exclusion. |

If hiding and excluding were one flag, a user tidying their sidebar would
silently change their reported net worth. There is a test asserting exactly
this.

**Archiving is never deletion.** The ledger lines behind a closed account are
immutable and still belong in historical reports. `DELETE` on the endpoint
archives.

A coupled correctness fix was required: `net_worth()` summed *all*
asset/liability balances. Adding exclusion flags without updating it would have
made them decorative.

### 1.3 API response type inconsistency — **FIXED**

Found while testing: account `create`/`patch` returned raw UUID objects while
`list` returned strings, because create bypassed the serializer. This quietly
breaks client-side identity comparison (`account.id === selectedId`). All
account responses now render through one serializer.

### 1.4 Investments have no cost basis — **NOT IMPLEMENTED** [unverified depth]

`AccountType.INVESTMENT` exists, but an investment account appears to be treated
as a cash-like balance. Without holdings, cost basis and unit quantities, the
product cannot show returns, allocation, or capital gains — and a net worth that
treats a brokerage as a static number will be wrong every single day.

I did not implement this: it is a new bounded context (holdings, price history,
lots), not a field addition, and doing it badly is worse than not doing it. It
is a blocker for anyone with investments, and *not* a blocker for a user
tracking cash accounts and cards — which is a legitimate v1 scope decision, but
it should be a deliberate one.

---

## 2. High Priority Enhancements

Expected by users of any modern personal finance app.

1. **Reconciliation workflow.** The ledger supports it structurally
   (immutable entries, materialized balances) but there is no "mark cleared /
   reconcile to statement" flow. This is the feature that converts a tracker
   into a system of record.
2. **Duplicate detection on import.** Re-importing an overlapping CSV date range
   is the single most common way users corrupt their own data.
3. **Merchant normalization.** `SQ *COFFEE 0123` and `SQ *COFFEE 0456` are the
   same merchant. Without this, category rules and merchant analytics are
   unreliable.
4. **Split transactions in the UI.** `split_transaction` exists in the service
   layer and `split_group` on the model — **[unverified]** whether the UI
   exposes it.
5. **Rollover budgets.** Envelope users consider this table stakes; the budget
   model would need a carry-forward concept.
6. **Debt payoff strategies** (snowball/avalanche). High perceived value,
   entirely derivable from existing liability accounts and interest rates —
   though interest rate is not currently a field.

## 3. Premium Features

Differentiators, all of which the current architecture supports cleanly.

1. **Cash flow forecasting from recurring + bills.** The scheduling data already
   exists; projecting balances forward is a selector, not a new context.
2. **Household roles beyond permissions** — partner mode, children's allowances,
   per-member visibility of specific accounts.
3. **"What changed this month?"** narrative summaries. The intelligence app and
   provider registry already exist to host this.
4. **Receipt scanning with OCR extraction** — attachments exist; extraction
   doesn't.
5. **Scenario modelling** — "what if I pay £200 more toward this card?"

## 4. Future Roadmap

Design now, build later.

1. **Bank aggregation** (Plaid / TrueLayer / GoCardless). `external_id` and
   `last_synced_at` fields already anticipate this, which is good forward
   design. The hard part is not the integration — it's the **duplicate and
   conflict resolution** between synced and manually-entered transactions, and
   that design should be settled before the first provider is wired.
2. **Multi-entity support** — separating personal from business ledgers within
   one household.
3. **Tax lot tracking** for investments, which depends on 1.4 landing first.
4. **Webhooks and public API.** The outbox pattern is already in place and is
   the correct foundation.

---

## Verification

| Layer | Result |
|---|---|
| Backend tests | **349 passing** (326 baseline + 23 new) |
| Frontend tests | **295 passing** across 61 files |
| TypeScript | Clean |
| Stylesheets | All 20 parse cleanly |
| Production build | Green |
| Lint | 1 pre-existing warning |

New backend coverage specifically asserts the properties that would fail
*silently* if broken: that the opening entry balances, that direction is correct
per account kind, that it is idempotent, that archiving moves nothing in the
ledger, and that hiding an account does **not** change net worth.

---

## Two notes on process

**A test I wrote failed for the right reason.** My first API test compared an
account id from a create response against one from a list response and failed —
because the two endpoints genuinely returned different types. The test found a
real defect rather than needing to be adjusted to pass. That is what these tests
are for.

**Environment failures are not product failures.** Three FX tests failed
mid-session and I nearly attributed it to my `net_worth()` change. It was a
stale reused test database (`--reuse-db` in `pytest.ini`) after adding a
migration. Always confirm with `--create-db` before believing a regression.
