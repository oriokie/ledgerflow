# `goals` — Financial Goals

A goal is a **lens over money that already exists**, not a ledger construct.
Setting a goal moves nothing; contributions record money the user has already
set aside. This is the single most important property of the module: inventing
transfers the bank never made would corrupt reconciliation, so the goals app
never posts a journal entry.

## Domain model

### `SavingsGoal`

| Field | Purpose |
|---|---|
| `kind` | Taxonomy — emergency fund, vacation, house deposit, education, retirement, vehicle, debt payoff, custom. Drives recommendations and default priority. |
| `target_minor` / `target_date` | What and by when. |
| `priority` | 1 (Critical) → 5 (Someday). Integer so ordering is a database concern; ascending order *is* funding order. |
| `tracking` | `manual` (sum of contributions) or `account_balance` (mirrors a linked account). |
| `planned_monthly_minor` | What the user *intends* to contribute. |
| `auto_contribute_*` | Standing monthly instruction. |
| `status` | active / paused / achieved / archived. |

### Three monthly amounts, deliberately separate

This is the design decision that makes the forecast useful:

| Amount | Source | Answers |
|---|---|---|
| **required** | target ÷ months remaining | What must I do? |
| **planned** | user input | What did I say I'd do? |
| **observed** | contribution history | What am I actually doing? |

Most goal trackers show only the first and become useless the moment a user
falls behind. Keeping all three lets the product say the genuinely useful
thing: *"you planned 300, you're doing 180, you need 420."*

## Forecasting engine (`apps/goals/forecasting.py`)

Everything is derived on read. Nothing is cached — a stored forecast is a
forecast that silently goes stale.

- `observed_monthly_rate_minor` — mean over a 6-month window, **including
  months with no contribution**. A goal funded twice in six months is not a
  300/month habit, and dropping empty months would claim it was.
- `contribution_consistency` — share of recent months funded. Distinguishes a
  habit from an intention when both share a mean.
- `required_monthly_minor` — ceil division, always. Rounding down finishes
  short.
- `projected_completion_date` — observed rate, falling back to the plan.
- `projection_series` — month-by-month curve for the chart, clamped at target.
- `success_probability` — see below.
- `forecast()` — everything above in one pass.

### `add_months` is calendar-safe

Adding one month to 31 January yields 28 (or 29) February, never 3 March. Naive
month arithmetic drifts every forecast that crosses a short month, and the drift
compounds.

### Success probability

```
ratio       = observed ÷ required
base        = logistic(4 × (ratio − 1))      # 0.5 at exactly on-pace
probability = base × (0.6 + 0.4 × consistency)
```

The logistic saturates: twice the required pace is reassuring but not certain;
half is discouraging but not impossible. The consistency term caps an erratic
saver, because a mean built from one large deposit is a weaker signal than the
same mean built from six regular ones.

**This is a calibrated heuristic, not a statistical guarantee.** It is labelled
as such in the code, and the UI shows it as a *band* ("On track to make it" /
"Could go either way" / "Unlikely at this pace") rather than a percentage —
rendering a heuristic to the point implies precision the model does not have,
and in a financial product that false precision is exactly what users would
rely on.

### The engine refuses to answer

`None` is returned — never a fabricated number — when:

- there is no target date (nothing to be on time for);
- fewer than 3 months have any contribution;
- the goal is not manually tracked, so no history exists;
- the projected date would be more than 50 years out.

A probability invented from two data points is worse than no probability,
because it looks like knowledge. Several tests exist solely to pin these
refusals. The UI renders each absence as an explanation, never as a zero.

## Recommendation engine (`apps/goals/recommendations.py`)

Two rules:

1. **Never recommend what already exists.** Kinds already covered by a live
   goal are filtered out first. Nagging about a goal the user already set is
   how software loses trust.
2. **Never invent a number.** Every target is computed from the user's own
   figures — emergency fund from measured expenses net of savings already held,
   debt payoff from actual card balances. Where the history isn't there, the
   recommendation is skipped rather than defaulted.

Returns an empty list rather than filler when the data supports nothing honest.

Retirement deliberately suggests a *habit* (10% of outgoings for a year), not a
projected retirement number: producing one requires assumptions about returns,
inflation, retirement age and state provision that this product does not hold
and should not silently invent.

## Auto-contribution

A standing instruction to log a contribution monthly. It records money the user
has already arranged to set aside — it does **not** move money.

- Day is capped at **1–28** so the instruction fires in every month. Allowing
  31 silently skips February.
- `run_due_auto_contributions()` is **idempotent per month** via
  `auto_contribute_last_run_on`. Running twice, or catching up after an outage,
  cannot double-fund a goal.
- Manual-tracking goals only; contributions are meaningless against a goal that
  mirrors an account balance.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/goals/goals/` | List goals with progress |
| `POST` | `/api/v1/goals/goals/` | Create (kind, priority, plan) |
| `PATCH` | `/api/v1/goals/goals/{id}/` | Update plan/presentation |
| `DELETE` | `/api/v1/goals/goals/{id}/` | Archive (not delete) |
| `GET` | `/api/v1/goals/goals/forecast/` | Forecasts for all live goals |
| `GET` | `/api/v1/goals/goals/{id}/forecast/` | Full forecast + projection + history |
| `GET` | `/api/v1/goals/goals/recommendations/` | Suggested goals |
| `PUT` | `/api/v1/goals/goals/{id}/auto-contribution/` | Set/clear the standing rule |
| `GET`/`POST` | `/api/v1/goals/goals/{id}/contributions/` | History / add |

`currency` and `tracking` are **not** updatable: both change how every
contribution already recorded should be read, so allowing edits would
reinterpret history rather than correct it.

## Integrations

- **Accounts** — `account_balance` tracking mirrors a linked account; the debt
  recommendation reads card balances.
- **Cashflow** — emergency-fund sizing uses `cashflow_statement`, inheriting its
  refusal to mix currencies.
- **Transactions** — `GoalContribution.source_transaction` links a contribution
  to the transfer that backs it (advisory).
- **Budgets** — shares the derive-on-read discipline; no stored progress.

## Scheduling

`goals.dispatch_auto_contributions` runs daily at 02:00 (after the recurring
transaction dispatcher, so a standing transfer into savings is already on the
ledger when the goal records it). It follows the same fan-out topology as the
alert sweep: stream active tenants, batch, and run one isolated per-tenant task
under its own RLS binding, so a slow or failing tenant can't hold up the rest.

A *daily* sweep is safe precisely because `run_due_auto_contributions` is
idempotent per goal per month. Trying to fire exactly once on each goal's chosen
day would be fragile — a missed run would silently skip a month — whereas a
daily sweep that no-ops on already-funded goals catches up automatically after
an outage.

## Multi-tenancy

`SavingsGoal` and `GoalContribution` extend `SoftDeletableModel`, inheriting
tenant scoping and row-level security (policies in
`notifications/migrations/0002_rls_new_tables.py`). Every selector and service
runs inside the tenant context; no query in this module filters by tenant by
hand.

## Testing

`tests/test_goal_forecasting.py` — 33 tests covering taxonomy and priority
defaults, calendar-safe month arithmetic, ceil-rounding of the required amount,
run-rate over empty months, consistency, projection and its refusals, the
probability model and its refusals, auto-contribution idempotency, and
recommendation de-duplication.

`GoalForecastPanel.test.tsx` — 10 tests, most asserting **honest degradation**:
that a missing probability renders an explanation rather than a zero, and that
confidence is banded rather than printed as a false-precision percentage.

`GoalRecommendations.test.tsx` — 6 tests, including that the panel renders
*nothing at all* when there are no suggestions rather than an empty-state
message, which would reintroduce the noise the engine exists to avoid.
