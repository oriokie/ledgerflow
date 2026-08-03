# LedgerFlow Intelligent Dashboard

`frontend/design-system/dashboard.html` is the intelligent dashboard. This
document explains its information architecture, the insight engine it
implies, and — the part that keeps "intelligent" honest — how every number
and every recommended action maps to capabilities the backend actually has.

## Information architecture: four questions, in priority order

The screen is organized as the sequence of questions a person actually
brings to their money, most urgent first. Each tier is quieter than the one
above it; detail lives behind disclosure, not on the surface.

| Tier | Question | Surface | Disclosure |
|---|---|---|---|
| 1 | **Can I spend?** | Safe to spend (hero) + compact net worth | "How this is calculated" — the exact arithmetic |
| 2 | **What needs my attention?** | ≤3 insight cards, severity-tiered | "Show the math" per card |
| 3 | **How am I doing?** | Budget meters + spending bars | — |
| 4 | **What happened?** | *Collapsed* recent activity | Expands to the 5-row ledger, links to full transactions |

## The hero is a derived number, not a raw balance

A checking balance answers the wrong question — it looks spendable while
rent, the card payment, and the rest of the grocery budget are already
spoken for. The hero is **Safe to spend**:

```
safe_to_spend = checking_balance
              − Σ upcoming recurring obligations before next income
              − Σ remaining budgeted essentials this period
```

Demo instance: $8,420.50 − $1,850.00 (rent, posts Aug 1) − $1,284.32 (Visa,
closes Jul 28) − $163.80 (budgeted essentials left) = **$5,122.38**. The
verification script recomputes this from the page's `data-sts` markers — a
derived number that doesn't equal its own disclosure fails the build.

Backend grounding, term by term: `account_current_balance_minor()`
(materialized, O(1)); `RecurringTransaction.next_run_on` within the window
(indexed on `(tenant_id, is_active, next_run_on)` — the scheduler's own hot
query); `budget_status(...).remaining_minor` summed over essential lines.
No new engine work is required to compute it — only a selector that
composes three existing reads.

## Insight catalog

Every insight is: **finding → why (data) → at most one action**. Severity
reuses the status tokens (attention = carmine, soon = amber, good =
verdant); no new colors, and carmine still never touches ordinary spending.

| Insight | Trigger (real data) | Action → real capability |
|---|---|---|
| Over-budget rebalance | `budget_status`: line `over_budget` **and** a sibling line has `remaining ≥ overage` | "Move $62 from Groceries" → update two `BudgetLine.limit_minor` values; month total unchanged |
| Statement due soon | `FinancialAccount` (liability) statement-close date within 7 days; balance from materialized `AccountBalance` | "Schedule payment" → `create_recurring_transaction(txn_type=TRANSFER, max_occurrences=1)` — a one-time scheduled transfer is a degenerate recurring transfer, which the engine already supports |
| Savings pace | `cash_flow(month)` income − expense, plus posted transfers to savings-type accounts | none — positive insights carry **zero** actions |
| Upcoming bill covered / not covered | next `RecurringTransaction` amount vs. current balance | "Top up checking" (transfer) only when not covered |
| Subscription creep (future) | recurring-source transactions grouped by normalized `Payee` | "Review subscriptions" — needs the payee normalization already built |

The demo shows the first three. The catalog is deliberately small: an
insight engine earns trust by being right and quiet, not prolific.

## Cognitive-load rules (enforced, not aspirational)

The verifier (`scripts/check_design_system.py`) mechanically enforces the
design rules, so they survive future edits:

1. **Derived numbers are honest** — safe-to-spend must equal its own
   disclosed inputs to the cent (`check_safe_to_spend`).
2. **One action per insight** — attention/soon cards carry exactly one
   button; **good cards carry none** (good news doesn't nag)
   (`check_insight_rules`).
3. **Every insight shows its work** — each card must contain a
   "show the math" disclosure (`check_insight_rules`).
4. Plus everything inherited: 64 WCAG contrast pairs, chart-bar
   proportionality, ledger running-balance arithmetic, token integrity,
   page wiring, HTML well-formedness.

Unenforceable-but-followed: at most three insights above the fold; tier 4
ships collapsed; disclosure is native `<details>` (keyboard/screen-reader/
no-JS for free); vocabulary is stable across surface and disclosure
("Schedule payment" schedules a payment — and the disclosure says exactly
what it will do and that it can be cancelled).

## What the app layer must add (honest gaps)

- A `safe_to_spend` selector composing the three existing reads (trivial),
  and marking which budget lines are "essential" (a boolean on
  `BudgetLine`).
- Statement-close date lives in `FinancialAccount.metadata` today; promote
  to a typed field when the bank-import pipeline lands.
- The rebalance action needs a `PATCH` for budget-line limits (the model
  supports it; the endpoint is a small addition).
- Insight dismissal/snooze state (per-user, per-insight) — a small table,
  not designed here.
