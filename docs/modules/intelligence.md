# `intelligence` — AI & Automation

Categorization, forecasting, health scoring, anomaly detection, and
recommendations — plus a separate, fully deterministic rule engine for
automation. Built around a **provider-strategy pattern** so LLMs can be
introduced later without any caller changing. See
[`../ARCHITECTURE.md#provider-strategy-pattern-ai--automation`](../ARCHITECTURE.md#provider-strategy-pattern-ai--automation)
for the design rationale.

## The protocol layer (`protocols.py`)

Five capabilities, each a `Protocol` (typed interface) + plain-dataclass
input/output DTOs — never a Django model, a prompt, or a vendor SDK type:

| Protocol | Method | Input DTO | Output DTO |
|---|---|---|---|
| `CategorizationProvider` | `suggest_category` | `TransactionFeatures` | `CategorySuggestion` |
| `ForecastProvider` | `forecast_expense` | `list[CashflowPoint]` | `Forecast` |
| `HealthScoreProvider` | `score` | `HealthInputs` | `HealthScore` |
| `AnomalyProvider` | `detect` | `list[AmountObservation]` | `list[Anomaly]` |
| `RecommendationProvider` | `recommend` | `RecommendationContext` | `list[Recommendation]` |

Every output carries a `Provenance` (`provider`, `kind` — rule/statistical/llm/
ensemble, `version`, `rationale`, `inputs_digest`) so a suggestion can always
be traced to what produced it. **Every output is advisory** — nothing in this
module writes to the ledger; a separate step (human accept, or an
auto-accept confidence threshold) applies it through the normal `finance`
service layer.

## Providers shipped today (all deterministic, zero external calls)

| Provider | File | Approach |
|---|---|---|
| `RuleBasedCategorizer` | `providers/rules.py` | Two tiers: merchant memory (reuse this payee's most recent category, confidence 0.95) → keyword rules (config-driven map, confidence 0.75) → abstain (confidence 0.0, `category_id=None`) rather than guess |
| `MovingAverageForecaster` | `providers/statistical.py` | Trailing-window average with a dispersion band — simple, transparent, a baseline any ML model must beat |
| `StatisticalAnomalyDetector` | `providers/statistical.py` | Z-score amount spikes (with a zero-variance fallback ratio), duplicate-charge detection (same payee+amount within days), new-payee-large-amount |
| `WeightedHealthScorer` | `providers/health.py` | Five components (savings rate, emergency fund, budget adherence, debt load, income stability), each 0–100, combined by fixed weights (`WEIGHTS`, sums to 1.0) into an overall score + plain-language band |
| `HeuristicRecommender` | `providers/recommend.py` | Reasons over a pre-computed `RecommendationContext`; every `action` payload maps to a capability the engine can actually execute — a recommendation the product can't back is worse than none |

The registry (`registry.py`) resolves each capability from
`INTELLIGENCE_PROVIDERS` (dotted path per capability; empty dict = these
defaults). **An LLM provider inherits these as its offline fallback** — the
product is fully functional with zero AI configuration.

## Domain model (persistence)

| Model | Purpose |
|---|---|
| `CategorizationSuggestion` | An advisory suggestion: `transaction`, `suggested_category`, `confidence`, `status` (`SuggestionStatus`: pending/accepted/rejected/superseded), provenance fields, `decided_at` |
| `AutomationRule` | User-defined if-this-then-that: `conditions` (JSON), `actions` (JSON), `priority` (lower runs first), `stop_processing`, `match_count`/`last_matched_at` bookkeeping |

## Automation engine (`automation.py`)

Deliberately **not** a code-eval system — a small, closed expression
language, evaluated purely and deterministically:

- **Conditions**: `{"all": [...]}` or `{"any": [...]}` of clauses
  `{"field", "op", "value"}`. Fields are allow-listed (`_ALLOWED_FIELDS`:
  `payee_normalized`, `memo`, `amount_minor`, `currency`, `account_type`,
  `category_id`); operators are a fixed set (`eq`, `contains`, `startswith`,
  `gte`/`lte`, `abs_gte`/`abs_lte`). Empty conditions never match — a rule
  must be explicit about its target.
- **Actions**: `ALLOWED_ACTION_TYPES = {"set_category", "add_tag", "flag_review"}`,
  validated against the allow-list at **save time** (`validate_actions`) so a
  bad rule never reaches execution — this is what lets rule bodies be
  flexible JSON without opening an arbitrary-write hole. A rule can never
  post, void, or move money.
- **Evaluation** (`evaluate_rules`): runs active rules in priority order,
  honors `stop_processing` (first match stops lower-priority rules from
  running).

## Application services (`services.py`)

| Function | Does |
|---|---|
| `features_for(txn)` | Builds the model-free `TransactionFeatures` DTO from a real transaction — the **only** place that reads Django models for categorization, keeping providers pure |
| `suggest_category(txn)` | Runs the configured categorizer, persists a `PENDING` suggestion |
| `accept_suggestion(suggestion)` / `reject_suggestion(suggestion)` | Applies via `finance_services.update_transaction` (never a raw write) / marks rejected. Idempotent on already-decided suggestions |
| `suggest_and_maybe_apply(txn)` | Suggests, and **auto-accepts** if confidence ≥ `INTELLIGENCE_AUTO_ACCEPT_CONFIDENCE` (default 0.9) AND the transaction is still uncategorized. This single dial moves the product between "assistive" and "autonomous" |
| `run_automation(txn)` | Evaluates active `AutomationRule`s, applies matched actions via `_apply_action` (which itself only ever calls `finance_services`/`tagging` functions), bumps `match_count`/`last_matched_at` |

## Composing selectors (`selectors.py`)

The **only** place that assembles the AI providers' inputs from real engine
reads — keeps providers pure/testable and gives "what data feeds the AI" one
auditable answer:

- `build_recommendation_context()` — over-budget/underspent lines from
  `budgeting.selectors.budget_status`, savings rate from `finance.selectors.cash_flow`
- `build_health_inputs()` — assets/liabilities from `finance.selectors.net_worth`
  (one aggregate query — an earlier per-account loop was an N+1, fixed; see
  `PERFORMANCE.md`), budget adherence, income stability (coefficient of
  variation over 3 months)
- `build_amount_observations()` — recent expense transactions as anomaly
  detector input (transfers excluded)

## API

Base path `/api/v1/intelligence/`.

| Method | Path | Purpose | Role |
|---|---|---|---|
| `GET` | `/suggestions/` | List categorization suggestions (optional `?status=`) | VIEWER |
| `POST` | `/suggestions/<id>/<accept\|reject>/` | Decide a suggestion | MEMBER |
| `GET` | `/health-score/` | Current health score + component breakdown (**cached**, TTL 300s) | VIEWER |
| `GET` | `/recommendations/` | Actionable recommendations (**cached**, TTL 300s) | VIEWER |
| `GET` | `/anomalies/` | Recent anomalies (**cached**, TTL 600s) | VIEWER |
| `GET`/`POST` | `/automation-rules/` | List / create rules (create validates the action allow-list, 422 if invalid) | VIEWER / MEMBER |
| `DELETE` | `/automation-rules/<id>/` | Deactivate (soft-delete) a rule | MEMBER |

The three cached endpoints use `apps.common.cache.cached_analytics` —
tenant-scoped, version-stamped keys, invalidated in O(1) whenever
`apps.finance.signals` fires on a financial write. See
[`common.md`](./common.md#caching-cachepy).

## Permissions

Standard `TenantScopedAPIView` + `IsTenantMember`; reads are VIEWER, decisions
and rule CRUD are MEMBER.

## Configuration

`INTELLIGENCE_PROVIDERS` (dict, dotted paths), `INTELLIGENCE_AUTO_ACCEPT_CONFIDENCE`
(default 0.9) — see [`../CONFIGURATION.md`](../CONFIGURATION.md).

## Extension points

This module *is* the extension point — see
[`../EXTENSION_POINTS.md#adding-an-llm-provider`](../EXTENSION_POINTS.md#adding-an-llm-provider)
and [`#adding-an-automation-action`](../EXTENSION_POINTS.md#adding-an-automation-action)
for the concrete steps. Two things worth internalizing before adding a
provider: (1) implement the `Protocol`, don't subclass a concrete provider —
protocols are structural, any class with the right method signature
satisfies one; (2) an ensemble (e.g. "ask the LLM only when rules abstain")
is itself just another class satisfying the same protocol, resolved by the
same registry.

## Testing

`tests/test_intelligence_providers.py` (28 pure-function tests — no DB, fixed
inputs/outputs, including the automation allow-list and condition-language
tests), `tests/test_intelligence_services.py` (DB-backed: suggestion
lifecycle, auto-accept threshold behavior, automation end-to-end against real
transactions under RLS). `tests/test_review_fixes.py` covers the two bugs a
prior review caught and fixed: `set_category` matching on the real `slug`
field (not the materialized `path`), and `flag_review` actually setting
`needs_review` rather than being a no-op.
