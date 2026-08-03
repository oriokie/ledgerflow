"""Provider protocol layer — the seam that lets LLMs slot in without a refactor.

Every AI capability in LedgerFlow is defined here as an abstract **protocol**
(a typed interface) plus plain-data DTOs for its inputs and outputs. Concrete
implementations live in `providers/`:

    CategorizationProvider   <- RuleBasedCategorizer   (today)
                             <- LLMCategorizer          (later, same interface)
    ForecastProvider         <- MovingAverageForecaster (today)
    HealthScoreProvider      <- WeightedHealthScorer    (today)
    AnomalyProvider          <- StatisticalAnomalyDetector (today)
    RecommendationProvider   <- HeuristicRecommender    (today)

Three rules make the seam hold:

1. **Interfaces speak domain, not model.** A provider takes a
   `TransactionFeatures` DTO and returns a `CategorySuggestion` DTO — never a
   Django model, a prompt, or a vendor SDK type. Swapping a rule engine for an
   LLM (or an ensemble of both) changes only which class the registry hands
   back; callers are untouched.

2. **Every output is advisory and carries provenance.** Providers return
   *suggestions* with a `confidence` and a `Provenance` (which provider,
   which version, why). Nothing here writes to the ledger. A separate
   application step (a human, or an automation rule) decides whether to act —
   so the immutable double-entry core is never at the mercy of a model.

3. **Determinism is a first-class capability, not a placeholder.** The
   rule-based providers are real, tested, and good enough to ship. The LLM is
   an upgrade path, not a dependency: the product works with zero external AI
   calls, which also gives every LLM provider a free offline fallback.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, runtime_checkable


# --------------------------------------------------------------------------- provenance
class ProviderKind(enum.StrEnum):
    RULE = "rule"
    STATISTICAL = "statistical"
    LLM = "llm"
    ENSEMBLE = "ensemble"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Attached to every AI output so a suggestion can always be traced to the
    thing that produced it — essential once rules and LLMs coexist and someone
    asks 'why was this suggested?'."""

    provider: str  # e.g. "RuleBasedCategorizer"
    kind: ProviderKind
    version: str  # bump when logic changes so stored suggestions stay interpretable
    rationale: str = ""  # human-readable "why"; an LLM fills this with its explanation
    inputs_digest: str = ""  # hash of the features seen, for reproducibility/debugging


# --------------------------------------------------------------------------- categorization
@dataclass(frozen=True, slots=True)
class TransactionFeatures:
    """Everything a categorizer may look at — deliberately model-free so the
    same DTO feeds a regex rule or an LLM prompt. Amounts are integer minor
    units, consistent with the engine."""

    payee_normalized: str
    memo: str
    amount_minor: int
    currency: str
    occurred_at: datetime
    account_type: str
    # optional richer context an LLM could use; rules may ignore it
    recent_category_ids_for_payee: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CategorySuggestion:
    category_id: str | None
    confidence: float  # 0..1
    provenance: Provenance
    # alternatives let the UI offer a pick-list and let an ensemble merge votes
    alternatives: tuple[tuple[str, float], ...] = ()


@runtime_checkable
class CategorizationProvider(Protocol):
    def suggest_category(self, features: TransactionFeatures) -> CategorySuggestion: ...


# --------------------------------------------------------------------------- forecasting
@dataclass(frozen=True, slots=True)
class CashflowPoint:
    period_start: date
    income_minor: int
    expense_minor: int


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    period_start: date
    projected_expense_minor: int
    low_minor: int  # confidence band
    high_minor: int


@dataclass(frozen=True, slots=True)
class Forecast:
    points: tuple[ForecastPoint, ...]
    provenance: Provenance


@runtime_checkable
class ForecastProvider(Protocol):
    def forecast_expense(self, history: list[CashflowPoint], periods_ahead: int) -> Forecast: ...


# --------------------------------------------------------------------------- health scoring
@dataclass(frozen=True, slots=True)
class HealthInputs:
    savings_rate: float  # 0..1 of income kept
    essential_coverage_months: float  # emergency-fund runway
    budget_adherence: float  # 0..1 of budget lines within limit
    debt_to_asset: float  # liabilities / assets, 0..1+
    income_stability: float  # 0..1, variance-derived


@dataclass(frozen=True, slots=True)
class HealthComponent:
    name: str
    score: int  # 0..100
    weight: float
    detail: str


@dataclass(frozen=True, slots=True)
class HealthScore:
    score: int  # 0..100 overall
    band: str  # "needs attention" | "fair" | "good" | "excellent"
    components: tuple[HealthComponent, ...]
    provenance: Provenance


@runtime_checkable
class HealthScoreProvider(Protocol):
    def score(self, inputs: HealthInputs) -> HealthScore: ...


# --------------------------------------------------------------------------- anomaly detection
@dataclass(frozen=True, slots=True)
class AmountObservation:
    transaction_id: str
    payee_normalized: str
    category_id: str | None
    amount_minor: int
    occurred_at: datetime


class AnomalyKind(enum.StrEnum):
    AMOUNT_SPIKE = "amount_spike"  # far above this payee/category's norm
    DUPLICATE = "duplicate"  # same payee+amount within a short window
    NEW_PAYEE_LARGE = "new_payee_large"  # first-ever payee, large amount
    RECURRING_MISSED = "recurring_missed"  # expected recurring charge absent


@dataclass(frozen=True, slots=True)
class Anomaly:
    transaction_id: str
    kind: AnomalyKind
    severity: float  # 0..1
    explanation: str
    provenance: Provenance


@runtime_checkable
class AnomalyProvider(Protocol):
    def detect(self, observations: list[AmountObservation]) -> list[Anomaly]: ...


# --------------------------------------------------------------------------- recommendations
class RecommendationKind(enum.StrEnum):
    BUDGET_REBALANCE = "budget_rebalance"
    BUDGET_CREATE = "budget_create"
    SUBSCRIPTION_REVIEW = "subscription_review"
    SAVINGS_OPPORTUNITY = "savings_opportunity"
    BILL_UPCOMING = "bill_upcoming"


@dataclass(frozen=True, slots=True)
class Recommendation:
    kind: RecommendationKind
    title: str
    body: str
    severity: str  # "attention" | "soon" | "good" — matches the dashboard insight tiers
    # a machine-actionable payload mapping to a REAL engine capability, e.g.
    # {"action": "budget_rebalance", "from_line": "...", "to_line": "...", "amount_minor": 6200}
    action: dict = field(default_factory=dict)
    provenance: Provenance = None  # type: ignore[assignment]


@runtime_checkable
class RecommendationProvider(Protocol):
    def recommend(self, context: RecommendationContext) -> list[Recommendation]: ...


@dataclass(frozen=True, slots=True)
class RecommendationContext:
    """Pre-computed, model-free snapshot the recommender reasons over. Built by
    a selector from real engine reads (budget_status, cash_flow, recurring
    schedules) so the recommender itself stays pure and testable."""

    over_budget_lines: tuple[dict, ...] = ()
    underspent_lines: tuple[dict, ...] = ()
    upcoming_bills: tuple[dict, ...] = ()
    savings_rate: float = 0.0
    currency: str = "USD"


# --------------------------------------------------------------------------- coaching
@dataclass(frozen=True, slots=True)
class CoachContext:
    """A model-free snapshot of everything the coach reasons over.

    Assembled by a selector from real engine reads — budget status, cash-flow
    statement, the cash-flow calendar, recurring schedules, goals, health score
    — so every provider, rule-based or LLM, sees identical structured inputs and
    neither has to touch the ORM.

    This is the contract that makes the LLM seam real. Swapping in a model means
    writing a prompt over *this* dataclass; it does not mean giving a model
    database access.
    """

    as_of: date
    currency: str
    #: {"limit_minor", "spent_minor", "category_id", "category_name", "percent"}
    budget_lines: tuple[dict, ...] = ()
    #: {"category_id", "category_name", "current_minor", "previous_minor", "delta_pct"}
    category_trends: tuple[dict, ...] = ()
    #: {"transaction_id", "payee", "amount_minor", "occurred_on"}
    large_transactions: tuple[dict, ...] = ()
    #: {"transaction_id", "payee", "amount_minor", "occurred_on", "duplicate_of"}
    possible_duplicates: tuple[dict, ...] = ()
    #: {"payee", "previous_minor", "current_minor", "delta_pct"}
    merchant_changes: tuple[dict, ...] = ()
    #: {"previous_minor", "current_minor", "delta_pct", "occurred_on"}
    income_changes: tuple[dict, ...] = ()
    #: {"name", "amount_minor", "frequency", "last_charged_on", "annual_minor"}
    subscriptions: tuple[dict, ...] = ()
    #: {"first_negative_on", "lowest_balance_minor", "lowest_balance_on"}
    cashflow_risk: dict = field(default_factory=dict)
    #: {"kind", "title", "rationale", "suggested_target_minor"}
    goal_suggestions: tuple[dict, ...] = ()
    #: {"account_id", "name", "balance_minor", "currency", "apr"}
    debts: tuple[dict, ...] = ()
    #: Pre-analysed debt observations from the debt module — promo expiries,
    #: rate rises, fee-heavy products, offset opportunities, milestones.
    debt_signals: tuple[dict, ...] = ()
    #: {"score", "band", "components": [{"name", "score", "detail"}]}
    health: dict = field(default_factory=dict)
    #: `None` when it couldn't be measured — distinct from a measured zero.
    savings_rate: float | None = None


@dataclass(frozen=True, slots=True)
class InsightCandidate:
    """A proposed insight, before it is scored and persisted.

    `rationale` and `evidence` are required by contract, not convention. An
    insight a user cannot check is one they cannot trust, and requiring both
    from every provider is what stops a future LLM from asserting something it
    has no figures to support.

    `dedupe_key` identifies the *condition*, never the run — see `Insight`.
    """

    kind: str
    severity: str
    title: str
    body: str
    rationale: str
    dedupe_key: str
    evidence: dict = field(default_factory=dict)
    action: dict = field(default_factory=dict)
    provenance: Provenance | None = None
    period_start: date | None = None
    period_end: date | None = None
    expires_on: date | None = None
    related_transaction_id: str | None = None
    related_category_id: str | None = None
    related_account_id: str | None = None
    #: Optional provider hint, 0..1, folded into the final priority score.
    confidence: float = 1.0


@runtime_checkable
class InsightProvider(Protocol):
    """Turns a context snapshot into candidate insights.

    A rule-based implementation ships today; an LLM implementation would take
    the same `CoachContext` and return the same `InsightCandidate` list, so the
    registry swap is the only change needed.
    """

    def generate(self, context: CoachContext) -> list[InsightCandidate]: ...


@dataclass(frozen=True, slots=True)
class BriefingDraft:
    headline: str
    summary: str
    metrics: dict = field(default_factory=dict)
    provenance: Provenance | None = None


@runtime_checkable
class NarrativeProvider(Protocol):
    """Writes the prose for a periodic review.

    Separated from `InsightProvider` deliberately: *detecting* a condition and
    *describing* it well are different problems with different failure modes.
    A deterministic detector paired with an LLM narrator is a genuinely useful
    configuration, and this split is what makes it expressible.
    """

    def write_briefing(
        self, *, period: str, context: CoachContext, insights: list[InsightCandidate]
    ) -> BriefingDraft: ...
