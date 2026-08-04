"""The commercial catalogue: what each tier actually includes.

Before this, a plan carried three gates — `max_accounts`, `max_members` and
`ai_insights` — so every tier above Free differed only in numbers. That makes a
pricing page hard to write and an upgrade hard to justify: "more accounts" is
not a reason to pay.

Feature names are declared here rather than as booleans on `Plan` for two
reasons. Adding a feature would otherwise mean a migration, which puts a
deploy between a commercial decision and its effect. And a name is checkable at
the call site — `ensure_feature(PlanFeature.DEBT_SCENARIOS)` says what it wants,
where `plan.tier != "free"` says only what it excludes today.

The tier→feature map is the single source of truth. `Plan.features` stays as an
override for one-off deals; the map is what a new plan gets by default.

Design principles applied here
------------------------------
* **Nothing that protects money is gated.** Reconciliation, the audit trail,
  data export and MFA are on every tier including Free. Charging for the ability
  to verify your own books, or to leave, would be indefensible.
* **Free is genuinely usable, not a demo.** One person, three accounts, real
  double-entry, budgets, and the full transaction history. The limit is scale,
  not capability.
* **Each tier answers one question.** Plus: "I want the planning tools."
  Family: "we need to share this." Business: "I need it for an organisation."
"""

from __future__ import annotations

from enum import StrEnum


class PlanFeature(StrEnum):
    """Gateable capabilities. The value is what appears in `Plan.features`."""

    # --- planning -------------------------------------------------------
    BUDGETS = "budgets"
    GOALS = "goals"
    RECURRING = "recurring"
    BILLS = "bills"
    DEBT_PLANNER = "debt_planner"
    #: Refinance, consolidation and stress modelling — the analyst-grade tools.
    DEBT_SCENARIOS = "debt_scenarios"
    INVESTMENTS = "investments"
    CASHFLOW_FORECAST = "cashflow_forecast"

    # --- intelligence ---------------------------------------------------
    #: The advisor layer: smart budget suggestions, financial independence,
    #: what-if scenarios and the periodic Financial Review.
    SMART_PLANNING = "smart_planning"
    AI_INSIGHTS = "ai_insights"
    AI_COACH = "ai_coach"
    ANOMALY_DETECTION = "anomaly_detection"
    AUTOMATION_RULES = "automation_rules"
    RECEIPT_SCANNING = "receipt_scanning"

    # --- reporting ------------------------------------------------------
    #: The 18-report library. Free gets the core dashboard, not the library.
    ADVANCED_REPORTS = "advanced_reports"
    SCHEDULED_REPORTS = "scheduled_reports"

    # --- collaboration --------------------------------------------------
    MULTI_MEMBER = "multi_member"
    ROLE_PERMISSIONS = "role_permissions"

    # --- operational ----------------------------------------------------
    PRIORITY_SUPPORT = "priority_support"
    API_ACCESS = "api_access"


#: Features every workspace gets, on any tier, forever.
#:
#: These are not withheld as an upsell because withholding them would be wrong
#: rather than merely stingy: a ledger you cannot reconcile is a ledger you
#: cannot trust, an audit trail you cannot read is no audit trail, and data you
#: cannot export is data held hostage. MFA is security, not a feature.
UNIVERSAL = frozenset(
    {
        "double_entry_ledger",
        "transactions",
        "categories_and_tags",
        "csv_import",
        "reconciliation",
        "audit_trail",
        "data_export",
        "mfa",
        "core_dashboard",
        "offline_pwa",
    }
)

F = PlanFeature

#: What each tier adds. Cumulative — every tier includes the ones before it.
#:
#: The live catalogue is **basic** and **plus** — two plans, one question:
#: "do you want the product to think with you, or just keep the books?"
#: Basic is the honest ledger: income, expenses, manual budgets, bills,
#: recurring and goals. Plus is everything the engine can do — investments,
#: debt, the cash-flow projection, the advisor layer, AI, automation, the
#: report library. The legacy tiers stay mapped so existing subscription rows
#: keep resolving; seed_plans retires their plan rows from sale.
TIER_FEATURES: dict[str, frozenset[PlanFeature]] = {
    "basic": frozenset({F.BUDGETS, F.BILLS, F.RECURRING, F.GOALS}),
    # Free: a real, permanently usable personal ledger for one person. The
    # constraint is scale (accounts, seats), not capability.
    "free": frozenset({F.BUDGETS, F.BILLS}),
    # Plus: the planning tools. This is the tier for someone who wants the
    # product to tell them something, not just record what happened.
    "plus": frozenset(
        {
            F.BUDGETS,
            F.BILLS,
            F.GOALS,
            F.RECURRING,
            F.DEBT_PLANNER,
            F.INVESTMENTS,
            F.CASHFLOW_FORECAST,
            F.ADVANCED_REPORTS,
            F.RECEIPT_SCANNING,
            F.ANOMALY_DETECTION,
            F.AI_INSIGHTS,
            F.AI_COACH,
            F.AUTOMATION_RULES,
            F.SMART_PLANNING,
            F.MULTI_MEMBER,
        }
    ),
    # Family: everything in Plus, plus the things that only matter when more
    # than one person is involved.
    "family": frozenset(
        {
            F.BUDGETS,
            F.BILLS,
            F.GOALS,
            F.RECURRING,
            F.DEBT_PLANNER,
            F.DEBT_SCENARIOS,
            F.INVESTMENTS,
            F.CASHFLOW_FORECAST,
            F.ADVANCED_REPORTS,
            F.SCHEDULED_REPORTS,
            F.RECEIPT_SCANNING,
            F.ANOMALY_DETECTION,
            F.AUTOMATION_RULES,
            F.SMART_PLANNING,
            F.AI_INSIGHTS,
            F.AI_COACH,
            F.MULTI_MEMBER,
            F.ROLE_PERMISSIONS,
        }
    ),
    # Business: everything, plus what an organisation needs operationally.
    "business": frozenset(PlanFeature),
}

#: Seats and accounts per tier. `None` means unmetered.
TIER_LIMITS: dict[str, dict[str, int | None]] = {
    "basic": {"max_members": 1, "max_accounts": 5},
    "free": {"max_members": 1, "max_accounts": 3},
    "plus": {"max_members": 2, "max_accounts": 25},
    "family": {"max_members": 6, "max_accounts": 100},
    "business": {"max_members": 25, "max_accounts": 500},
}

#: Suggested pricing, in minor units of the plan's currency. Monthly; the
#: annual equivalent is ten months' price, which is the conventional two-months-
#: free framing and keeps the arithmetic obvious on a pricing page.
TIER_PRICING_USD: dict[str, int] = {
    "basic": 300,
    "free": 0,
    "plus": 700,
    "family": 1400,
    "business": 4900,
}

#: Days a new workspace may use Basic before choosing a plan. Card-free by
#: design: a trial that demands payment details first is measuring willingness
#: to cancel, not willingness to pay.
TRIAL_DAYS = 7

#: The tiers currently offered for sale. Everything else is legacy: kept in
#: the maps so old subscription rows resolve, retired from the catalogue by
#: seed_plans.
LIVE_TIERS = ("basic", "plus")

#: One sentence per tier, for the pricing page and the admin console.
TIER_PITCH: dict[str, str] = {
    "basic": "The honest ledger: income, expenses, budgets, bills and goals.",
    "free": "A real double-entry ledger for one person. Not a trial.",
    "plus": "Planning tools: goals, debt payoff, investments and the full report library.",
    "family": "Everything in Plus, shared — up to six people with roles and permissions.",
    "business": "Everything, with API access and priority support.",
}


#: Human names for every gateable and universal feature. Held server-side so
#: the landing page, the in-app billing screen and the console all print the
#: same words — three hand-maintained label maps would drift, and a pricing
#: page that names a feature differently from the screen that enforces it
#: reads as two products.
FEATURE_LABELS: dict[str, str] = {
    # universal
    "double_entry_ledger": "Real double-entry ledger",
    "transactions": "Unlimited transactions",
    "categories_and_tags": "Categories and tags",
    "csv_import": "CSV statement import",
    "reconciliation": "Reconciliation",
    "audit_trail": "Immutable audit trail",
    "data_export": "Export everything, always",
    "mfa": "Two-factor authentication",
    "core_dashboard": "Core dashboard",
    "offline_pwa": "Works offline",
    # gateable
    str(PlanFeature.BUDGETS): "Budgets",
    str(PlanFeature.GOALS): "Savings goals",
    str(PlanFeature.RECURRING): "Recurring transactions",
    str(PlanFeature.BILLS): "Bill tracking",
    str(PlanFeature.DEBT_PLANNER): "Debt payoff planner",
    str(PlanFeature.DEBT_SCENARIOS): "Debt scenarios and stress tests",
    str(PlanFeature.INVESTMENTS): "Investment tracking",
    str(PlanFeature.CASHFLOW_FORECAST): "Day-by-day cash-flow forecast",
    str(PlanFeature.SMART_PLANNING): "Smart budgets, FI projection, scenarios & the Financial Review",
    str(PlanFeature.AI_INSIGHTS): "AI insights",
    str(PlanFeature.AI_COACH): "AI coach",
    str(PlanFeature.ANOMALY_DETECTION): "Anomaly detection",
    str(PlanFeature.AUTOMATION_RULES): "Automation rules",
    str(PlanFeature.RECEIPT_SCANNING): "Receipt scanning",
    str(PlanFeature.ADVANCED_REPORTS): "Full report library",
    str(PlanFeature.SCHEDULED_REPORTS): "Scheduled reports",
    str(PlanFeature.MULTI_MEMBER): "Shared workspace",
    str(PlanFeature.ROLE_PERMISSIONS): "Roles and permissions",
    str(PlanFeature.PRIORITY_SUPPORT): "Priority support",
    str(PlanFeature.API_ACCESS): "API access",
}


def label_for(feature: str) -> str:
    """Human name for a feature slug. Falls back to the slug made readable —
    a new feature must never render as a blank on the pricing page."""
    return FEATURE_LABELS.get(str(feature), str(feature).replace("_", " ").capitalize())


def features_for(tier: str) -> frozenset[PlanFeature]:
    return TIER_FEATURES.get(tier, frozenset())


def resolved_features(plan) -> list[str]:
    """What a plan actually includes: its tier's defaults plus its own
    overrides — the same union `entitlements.resolve_entitlements` enforces.
    Sorted so payloads are stable for tests and caches."""
    declared = {str(f) for f in (plan.features or [])}
    inherited = {str(f) for f in features_for(plan.tier)}
    return sorted(declared | inherited)


def includes(tier: str, feature: PlanFeature | str) -> bool:
    """Whether a tier includes a feature. Universal features are always true."""
    if str(feature) in UNIVERSAL:
        return True
    return PlanFeature(str(feature)) in features_for(tier)


def catalogue() -> list[dict]:
    """The full catalogue, for a pricing page or the admin console.

    `adds` lists only what is new at that tier, because a pricing table that
    repeats every feature at every level is unreadable — the question a reader
    has is "what do I get by moving up".
    """
    order = ["free", "plus", "family", "business"]
    rows = []
    previous: frozenset[PlanFeature] = frozenset()
    for tier in order:
        current = features_for(tier)
        rows.append(
            {
                "tier": tier,
                "pitch": TIER_PITCH[tier],
                "price_minor": TIER_PRICING_USD[tier],
                "currency": "USD",
                **TIER_LIMITS[tier],
                "features": sorted(str(f) for f in current),
                "adds": sorted(str(f) for f in current - previous),
                "universal": sorted(UNIVERSAL),
            }
        )
        previous = current
    return rows
