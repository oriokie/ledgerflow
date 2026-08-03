# LedgerFlow — Personal Finance Feature Gap Analysis

> **STATUS UPDATE — all gaps below have now been implemented.** This document
> is retained as the rationale record; the sections below describe the gaps as
> they were *before* implementation. What shipped, and where to find it:
>
> | Gap | Status | Where |
> |---|---|---|
> | A1 Savings goals | ✅ Shipped | `apps/goals/` — `SavingsGoal`/`GoalContribution`, manual + account-balance tracking, `/api/v1/goals/` |
> | A2 Transaction search/filtering | ✅ Shipped | `selectors.TransactionFilters` + `GET /finance/transactions/` (date, category, payee, tag, type, amount range, text, status) |
> | A3 Bank/statement import | ✅ Shipped (CSV) | `apps/finance/import_csv.py`, `POST /finance/transactions/import/` — idempotent; Plaid-style aggregators remain the larger later build |
> | A4 Notifications/alerts | ✅ Shipped | `apps/notifications/` — inbox, dedupe, budget/large-txn/bill/goal producers, daily beat sweep |
> | A5 Data export | ✅ Shipped | `GET /finance/transactions/export/` streaming CSV (honors all filters) |
> | A6 Split transactions | ✅ Shipped | `services.split_transaction` + `POST /finance/transactions/{id}/split/` |
> | A7 Net-worth history / trends | ✅ Shipped | `intelligence.selectors.net_worth_history` / `spending_trend`, `/intelligence/net-worth-history/` + `/spending-trend/` |
> | A8 Bill management | ✅ Shipped | `apps/finance/bills.py` + `Bill` model, `/finance/bills/`, feeds recommender's `upcoming_bills` |
> | B1 Forecasting wire-up | ✅ Shipped | `intelligence.services.forecast` + `/intelligence/forecast/` |
> | B2 Duplicate/missed-recurring | ✅ Shipped | `intelligence.services.detect_missed_recurring`, merged into `/intelligence/anomalies/` |
> | B3 Auto-categorization on create | ✅ Shipped | `apps/intelligence/signals.py` — post-commit pipeline, re-entrancy-guarded |
>
> Coverage: 32 new tests (splits, filtering, goals, bills, notifications,
> forecast, import, missed-recurring, alert-sweep task, cross-tenant
> isolation). Full suite 258 passing; ruff/black clean; `check --deploy` clean;
> no migration drift. New tenant-owned tables are RLS-protected
> (`notifications/migrations/0002_rls_new_tables.py`). Items under **C.
> Deliberately deferred** below remain deferred by design.

---

Assessment of what a complete personal-finance product offers versus what
LedgerFlow currently ships, grounded in the actual code (services, selectors,
API routes, models — not the roadmap docs). Gaps are sorted into three
buckets:

- **A. Missing entirely** — no model, service, or endpoint exists.
- **B. Built but not shipped** — the hard part exists in code but nothing
  exposes it to a user.
- **C. Deliberately deferred** — already acknowledged in the codebase/docs as
  out of scope for now, listed for completeness.

The engine underneath is strong: double-entry ledger, multi-currency accounts,
categories, transfers, recurring schedules, budgets, tags, payees, receipt
attachments, net worth, cash flow, category breakdown, account statements, an
advisory AI layer, and rule-based automation. The gaps below are mostly
**product surface** (things a user does with that engine) rather than
foundational.

---

## A. Missing entirely

### A1. Savings goals / financial goals — *high impact*
There is no `Goal` model anywhere. "Save $5,000 for a vacation by December,"
"build a 3-month emergency fund," progress tracking against a target — none of
this exists. This is table-stakes for a consumer finance product (YNAB, Monarch,
Copilot, Revolut Pockets all have it) and the health scorer already *computes*
emergency-fund coverage, so the data to power goals is right there. A goal is
a small model (target amount, target date, linked account(s), contributions)
plus a progress selector.

### A2. Transaction search & filtering — *high impact, small effort*
The transaction list endpoint (`GET /finance/transactions/`) filters by
**`account_id` only**. There is no date-range, category, payee, amount-range,
tag, status, or free-text (memo/payee) filter — and no full-text search at all
(`grep` for "search" returns nothing in the app). For anyone with more than a
few hundred transactions this makes the ledger hard to actually use. The
indexes to support most of these filters already exist on `Transaction`; this
is mostly a serializer + `django-filter` FilterSet wiring job.

### A3. Bank connection / statement import — *high impact, large effort*
No import path of any kind: no CSV/OFX/QIF upload, no Plaid/TrueLayer/MX
aggregator integration. The scaffolding is present and pointed at — the
`Institution` model has an `aggregator` field commented "plaid/truelayer/...",
`Transaction` has `external_id` with an idempotent-import unique constraint,
and `TransactionStatus.PENDING` plus `TransactionSource.IMPORTED` exist — but
nothing populates them. Every transaction today is manual entry. This is the
single biggest driver of real-world usefulness and is explicitly the
"recommended next major build" in the codebase notes; calling it out here so
it isn't lost.

### A4. Notifications / alerts — *high impact*
The only outbound message the system sends is an invitation email
(`tenancy/tasks.py`). There is no notification model, no delivery for: budget
overspend, low balance, large/unusual transaction, upcoming bill, a bill that
*didn't* arrive, goal milestones, or a new anomaly. The anomaly detector and
budget-status selector already produce exactly the signals a notification
system would fire on — they're computed and then nowhere delivered. Needs a
`Notification` model + preferences + a delivery channel (email to start, push
later).

### A5. Data export — *medium impact, small effort, often a compliance requirement*
No export of any kind (`grep` "export" → nothing). Users can't download their
transactions as CSV, and there is no "export all my data" for GDPR/portability.
For a finance product holding someone's complete financial history, data
portability is close to mandatory in several jurisdictions. A CSV/JSON export
endpoint over the existing selectors is small.

### A6. Split transactions — *medium impact*
A single purchase can't be split across categories (e.g. a $200 Target
receipt = $150 groceries + $50 household). One `Transaction` maps to exactly
one `category`. This is a common real need and a known personal-finance
feature. It fits the ledger model cleanly (a split is a journal entry with
more than two lines — one credit to the account, N debits to N category
accounts), so the accounting core already supports it; only the domain/API
layer is missing.

### A7. Net-worth history / balance trends over time — *medium impact*
`net_worth()` and `account_current_balance_minor()` return the balance **right
now**. There is no time series — no "net worth over the last 12 months," no
balance-history chart data, no month-over-month spending trend endpoint. The
immutable ledger contains everything needed to reconstruct historical balances
(`account_statement` already does a running balance for one account over a
window), but there's no selector that returns net worth or category spend as a
dated series for charting. Most finance dashboards lead with this chart.

### A8. Bill management / upcoming-bill tracking — *medium impact*
`RecurringTransaction` auto-*posts* on schedule, but there's no concept of a
**bill you owe that's coming due** and can mark paid, nor a "what's due in the
next 14 days" view. The recommender's `RecommendationContext` even has an
`upcoming_bills` field — currently always empty (`()`), waiting on a
typed statement/due-date. This is the difference between "money already left
your account" and "money is *about* to."

---

## B. Built but not shipped (wire-up only)

### B1. Cash-flow forecasting — *provider done, zero exposure*
`MovingAverageForecaster` (`intelligence/providers/statistical.py`) is fully
implemented and unit-tested (`test_intelligence_providers.py`), but
`get_forecaster()` is called by nothing — no selector builds its
`CashflowPoint` history input, and no endpoint returns a `Forecast`. "Here's
what your spending looks like next month" is computed-capable today and
invisible to users. Wiring: one selector (build history from `cash_flow` over
past periods) + one endpoint.

### B2. Duplicate & new-payee anomaly surfacing — *detector done, partially exposed*
`StatisticalAnomalyDetector` implements amount-spike, duplicate, and
new-payee-large detection, and `GET /intelligence/anomalies/` exposes it — so
this is mostly shipped. But two declared anomaly kinds have **no detector
behind them**: `RECURRING_MISSED` (an expected recurring charge didn't arrive)
and the `SUBSCRIPTION_REVIEW` recommendation kind. These are enum values with
no implementation — either build them or they're dead vocabulary.

### B3. Auto-categorization on new transactions — *service done, not triggered*
`suggest_and_maybe_apply()` and `run_automation()` exist and are tested, but
nothing calls them automatically when a transaction is created — there's no
hook in `record_expense`/`record_income` or a post-create signal. Today a
suggestion only happens if something explicitly asks for one. The moment
import (A3) lands this becomes essential; even for manual entry, running
automation rules on create is expected behavior.

---

## C. Deliberately deferred (already acknowledged in code/docs)

These are real gaps but already documented as conscious scope decisions —
listing them so the picture is complete:

- **Cross-currency transactions/transfers** — `fx.ExchangeRate` exists as
  reference data; no conversion service. Selectors correctly refuse to sum
  across currencies. (See `docs/modules/fx.md`.)
- **Multi-period budget rollover** — only single-period carry-forward today.
- **`essential` flag on budget lines** → a `safe_to_spend` composing selector
  for the dashboard "can I spend?" hero — designed, not built.
- **LLM providers** — the provider-strategy seam is built; only deterministic
  providers ship.
- **Custom per-tenant roles**, **SMS MFA** — acknowledged scope limits.
- **Investment/holdings tracking** — `AccountType.INVESTMENT` exists as an
  account type, but there's no positions/holdings/cost-basis/ticker model. A
  true investment tracker (shares, market value, gain/loss) is a separate
  subsystem, reasonably out of scope for a v1 budgeting-first product but worth
  naming.

---

## Recommended priority order

If the goal is the most product value per unit effort, grounded in what the
engine already supports:

1. **Transaction search/filtering (A2)** — small effort, immediately makes the
   existing ledger usable at real data volumes. Indexes already exist.
2. **Forecasting wire-up (B1)** + **net-worth history (A7)** — high-visibility
   dashboard features; the forecaster is already built, and history is a new
   selector over the immutable ledger.
3. **Savings goals (A1)** — high user value, small model, and the health
   scorer already models the underlying data.
4. **Notifications (A4)** — the signals (anomalies, budget status) already
   exist; this is delivery infrastructure.
5. **Split transactions (A6)** — the ledger already supports N-line entries;
   only the domain/API layer is missing.
6. **Data export (A5)** — small, and likely a compliance requirement before
   real users.
7. **Bank/statement import (A3)** — the largest and highest-impact build; the
   idempotency/status/source scaffolding is already in place for it.

Everything above is additive on top of a sound engine — none of it requires
reworking the ledger, tenancy, or the double-entry core.
