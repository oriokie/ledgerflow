# LedgerFlow AI & Automation Architecture

This document defines how LedgerFlow does intelligent categorization, spending
analysis, budgeting recommendations, financial-health scoring, anomaly
detection, forecasting, and rule-based automation — and, crucially, how it does
all of that today with **zero external AI calls** while leaving a seam where
LLMs slot in later **without a refactor**.

Everything lives in `apps/intelligence/`. It is a leaf app: it depends on
`finance` and `budgeting`, and nothing depends on it, so it can evolve (or be
replaced) freely.

## Two load-bearing decisions

### 1. Provider-strategy: capabilities are interfaces, implementations are swappable

Every AI capability is an abstract **protocol** (`apps/intelligence/protocols.py`)
plus model-free DTOs for its inputs and outputs. Implementations live in
`providers/`, and a config-driven **registry** (`registry.py`) decides which one
answers:

```
CategorizationProvider   <- RuleBasedCategorizer        (ships today)
                         <- LLMCategorizer               (later, same interface)
ForecastProvider         <- MovingAverageForecaster      (ships today)
HealthScoreProvider      <- WeightedHealthScorer         (ships today)
AnomalyProvider          <- StatisticalAnomalyDetector   (ships today)
RecommendationProvider   <- HeuristicRecommender         (ships today)
```

Because the interface speaks the domain (`TransactionFeatures` in,
`CategorySuggestion` out) and never a model, a prompt, or a vendor SDK type,
adding an LLM is a settings change:

```python
INTELLIGENCE_PROVIDERS = {
    "categorization": "apps.intelligence.providers.llm.LLMCategorizer",
}
```

No caller is touched. An **ensemble** provider is the same move — it can take
the rule engine's merchant-memory as a strong prior and consult an LLM only on
low-confidence, first-time payees (the expensive minority), keeping cost and
latency bounded.

### 2. Advisory, not autonomous: the ledger is never at the mercy of a model

The immutable double-entry engine is the source of truth, and no AI component
writes to it. Instead:

- Providers return **suggestions** carrying a `confidence` and a `Provenance`
  (which provider, which version, and a human-readable "why").
- A categorization suggestion is **persisted as an advisory record**
  (`CategorizationSuggestion`, status `pending`) and only ever applied through
  the existing finance service layer (`update_transaction`) — by a human tap or
  by an auto-accept rule above a configurable confidence threshold.
- Automation actions are drawn from a fixed **allow-list** (categorize, tag,
  flag) and likewise run through finance services; a rule can never post, void,
  or move money.

So the worst a misbehaving model can do is propose a bad category that a person
declines. Every application of an AI output is consented-to and audit-logged,
and the ledger's guarantees are untouched. The single dial between "assistive"
and "autonomous" is `INTELLIGENCE_AUTO_ACCEPT_CONFIDENCE`.

## Capabilities

### Intelligent transaction categorization
`RuleBasedCategorizer` works in two tiers, cheapest first: (1) **merchant
memory** — reuse the category this payee last received, high confidence, which
is where most real accuracy comes from and improves automatically as the user
categorizes; (2) **keyword rules** for first-time payees. With no signal it
**abstains** (returns `None`) rather than guessing — an honest abstention is
exactly the input an LLM tier is later asked to improve. `services.suggest_and_maybe_apply`
stores the suggestion and auto-applies only when confidence clears the
threshold and the transaction is still uncategorized.

### Spending analysis & forecasting
`category_breakdown` and `cash_flow` already exist as engine selectors (transfers
excluded — moving money isn't spending). `MovingAverageForecaster` projects
future expense from a trailing window with a ±1σ band: transparent, stable on
short histories, and a baseline any future ML must beat before it earns its
complexity.

### Budgeting recommendations
`HeuristicRecommender` reasons over a pre-computed, model-free
`RecommendationContext` (built by a selector from `budget_status`, `cash_flow`,
and recurring schedules) and emits recommendations whose `action` payloads map
to **real engine capabilities**: a budget-rebalance is a pair of budget-line
limit edits; an upcoming-bill is a one-time scheduled transfer
(`max_occurrences=1`). Severity mirrors the dashboard's insight tiers, and —
consistent with that design — positive recommendations carry no action.

### Financial health scoring
`WeightedHealthScorer` produces a 0–100 score and a plain-language band from
five explicit, weighted components (savings rate, emergency-fund runway, budget
adherence, debt load, income stability). Weights sum to 1.0 (asserted in tests)
and every component ships a one-line explanation — a score you can decompose,
not a horoscope.

### Anomaly detection
`StatisticalAnomalyDetector` flags amount spikes (z-score within a payee's own
history, with a ratio fallback when the history has zero variance), duplicate
charges (same payee+amount within three days), and large first-time payees.
Every flag explains itself in one sentence, because it interrupts the user.

### Rule-based automation
`AutomationRule` is deterministic if-this-then-that over transactions. Conditions
are a small closed expression language (`all`/`any` of field-op-value clauses
over an allow-listed set of fields); actions are allow-listed. `automation.py`
evaluates rules in priority order and honors `stop_processing`. Pure,
inspectable, and trustworthy — precisely the property that lets us store rule
bodies as flexible JSON without opening a hole.

## Where the LLM plugs in (and where it never does)

| LLM may… | LLM never… |
|---|---|
| Implement a provider behind an existing protocol (categorize, explain a health score, narrate a forecast) | Write to the ledger |
| Author automation rules from natural language, emitting the same validated JSON for user confirmation | Execute automation or bypass the allow-list |
| Break ties an ensemble routes to it on low confidence | Auto-apply below the confidence threshold |
| Fill the `rationale` field with a real explanation | Replace the deterministic math it narrates |

The LLM is always a provider *behind* the seam or an author *in front of* the
confirmation step — never in the execution path of a financial write.

## Verification

`tests/test_intelligence_providers.py` (28 pure tests, no DB) proves every
provider satisfies its protocol and returns provenance-stamped DTOs — i.e. the
swappable seam holds — and covers the categorizer tiers/abstention, forecast
math, health weighting/transparency, all anomaly kinds (including the
zero-variance spike case found during testing), recommender action-mapping, and
the automation condition/allow-list/priority rules.

`tests/test_intelligence_services.py` (9 DB + RLS tests) proves the advisory
lifecycle end-to-end: suggestions store as `pending` without touching the
transaction; accept applies through the finance layer; reject leaves it
uncategorized; the confidence threshold gates auto-apply; automation sets
category/tag through finance services and honors priority+stop; and
suggestions are tenant-isolated by row-level security. Both intelligence tables
have forced RLS.

Full suite: **211 passing** (was 174 before this component; +37). `ruff` and
`black` clean, no migration drift, `check --deploy` clean.

## Deferred (documented, not hidden)

- Actual LLM provider implementations and the ensemble router (the seam is
  built and tested; the implementations are a follow-up).
- Insight snooze/dismiss state (a small per-user table).
- A `safe_to_spend` composing selector and an "essential" flag on budget lines
  (also called for by the intelligent dashboard).
- Statement-close date as a typed field (arrives with the bank-import
  pipeline), which would also feed subscription-creep detection via the payee
  normalization already built.
