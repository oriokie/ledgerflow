# `budgeting` — Budgets & Actual-vs-Budget Reporting

A read-heavy overlay on top of `finance`. Budgets never touch the ledger —
they compare a configured limit against actual posted spending, computed on
read, not maintained as a running counter.

## Domain model

| Model | Purpose | Key fields |
|---|---|---|
| `Budget` | A named budget over a recurring period | `period` (`BudgetPeriod`), `currency`, `starts_on` (the anchor date every period is computed relative to), `is_active` |
| `BudgetLine` | One category's limit within a budget | `budget`, `category` (must be `CategoryKind.EXPENSE`), `limit_minor`, `rollover` (carry unspent to next period) |

`BudgetPeriod`: `weekly`, `monthly`, `quarterly`, `yearly`. Unique constraint:
one `BudgetLine` per `(budget, category)` among live rows.

## Service layer (`services.py`)

`create_budget(name, currency, starts_on, period)`, `add_budget_line(budget,
category, limit_minor, rollover)` — validates `limit_minor >= 0` and that the
category is an expense category (`BudgetError` otherwise). That's the entire
write surface; everything else in this module is read-only.

## Selectors (`selectors.py`) — the interesting part

`period_bounds(period, starts_on, as_of)` computes `[start, end)` of the
period containing `as_of`, aligned to the budget's anchor date — not
calendar-month boundaries, the budget's *own* period boundaries (a budget
starting on the 15th has periods running 15th-to-15th).

`_actual_spend_minor(category, start, end)` sums spend over the category's
**whole subtree** using the materialized `path` (a single `path LIKE
'food.%'` range condition) — no recursive CTE needed because `finance.Category`
already maintains `path`/`depth` on write.

`budget_line_status(line, as_of)` → `BudgetLineStatus` dataclass:
`limit_minor`, `carried_minor` (previous period's unspent, if `rollover=True`
and there was a previous period), `effective_limit_minor` (`limit + carried`),
`actual_minor`, plus computed `remaining_minor`, `percent_used`, `over_budget`
properties. **Rollover is single-period** — carries forward only the
immediately-preceding period's unspent amount, not a deeper multi-period
accumulation; this is a deliberate scope decision to bound the cost of a
status read (see the module docstring), documented as an extension point if
deeper carry-forward is ever needed.

`budget_status(budget, as_of)` → `list[BudgetLineStatus]` for every line in
the budget, `select_related("category", "budget")`'d to avoid N+1.

## API

Base path `/api/v1/budgeting/`.

| Method | Path | Purpose |
|---|---|---|
| `GET`/`POST` | `/budgets/` | List / create budgets |
| `GET`/`POST` | `/budgets/<id>/lines/` | List / add budget lines |
| `GET` | `/budgets/<id>/status/` | `budget_status()` for every line — the actual-vs-budget view |

## Permissions

Standard `TenantScopedAPIView` + `IsTenantMember`, `WriteRequiresMemberMixin`
(VIEWER for reads, MEMBER to create budgets/lines).

## Extension points

- **Multi-period rollover** — `budget_line_status` currently looks back
  exactly one period; a deeper carry-forward would extend the rollover
  calculation to walk back further, bounded by a configurable max, without
  changing the `BudgetLineStatus` contract.
- **`essential` flag on `BudgetLine`** — documented but not yet built; would
  feed a `safe_to_spend` composing selector (balance minus upcoming bills
  minus budgeted essentials) for a dashboard "can I spend?" view. See
  `apps.intelligence`'s `RecommendationContext.upcoming_bills`, which awaits
  the same typed-statement-date work.

## Testing

`tests/test_budgets.py` — limit validation, category-kind enforcement,
subtree spend aggregation across a category hierarchy, rollover math, period
boundary computation across period types.
