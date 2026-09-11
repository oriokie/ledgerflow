import {
  AlertTriangle,
  ArrowDownRight,
  ArrowLeftRight,
  Banknote,
  Calendar,
  Copy,
  CreditCard,
  Flag,
  HeartPulse,
  Landmark,
  Percent,
  PiggyBank,
  Receipt,
  Repeat,
  Target,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import type { InsightKind, InsightSeverity } from "../../api/types";

export const INSIGHT_ICONS: Record<InsightKind, LucideIcon> = {
  spending_anomaly: TrendingUp,
  overspending: AlertTriangle,
  overspend_pace: TrendingUp,
  budget_recommendation: Wallet,
  savings_opportunity: PiggyBank,
  duplicate_transaction: Copy,
  large_purchase: Receipt,
  merchant_change: ArrowDownRight,
  salary_change: Banknote,
  cashflow_risk: AlertTriangle,
  subscription_review: Repeat,
  goal_recommendation: Target,
  debt_recommendation: CreditCard,
  health_improvement: HeartPulse,
  promo_expiry: Percent,
  rate_increase: TrendingUp,
  refinance_opportunity: Landmark,
  high_fees: Receipt,
  offset_opportunity: ArrowLeftRight,
  debt_milestone: Flag,
  safe_to_spend: Wallet,
  committed_income: Percent,
  bill_due: Calendar,
};

export const INSIGHT_KIND_LABELS: Record<InsightKind, string> = {
  spending_anomaly: "Spending anomaly",
  overspending: "Over budget",
  overspend_pace: "On pace to overspend",
  budget_recommendation: "Budget",
  savings_opportunity: "Savings",
  duplicate_transaction: "Possible duplicate",
  large_purchase: "Large purchase",
  merchant_change: "Price change",
  salary_change: "Income change",
  cashflow_risk: "Cash flow",
  subscription_review: "Subscriptions",
  goal_recommendation: "Goal",
  debt_recommendation: "Debt",
  health_improvement: "Financial health",
  promo_expiry: "Promo ending",
  rate_increase: "Rate increase",
  refinance_opportunity: "Refinance",
  high_fees: "High fees",
  offset_opportunity: "Offset",
  debt_milestone: "Debt milestone",
  safe_to_spend: "Safe to spend",
  committed_income: "Committed income",
  bill_due: "Bill due",
};

/**
 * How each severity is presented.
 *
 * `critical` is the only one that gets a filled, alarming treatment, matching
 * the backend's discipline that it's reserved for things with a deadline. If
 * every severity looked urgent, none would read as urgent.
 */
export const SEVERITY_LABELS: Record<InsightSeverity, string> = {
  critical: "Needs attention",
  warning: "Worth a look",
  opportunity: "Opportunity",
  info: "For information",
};

/** Where each insight's primary action should take the user.
 *
 * Mapped from the backend's `action.action` verb rather than guessed from the
 * insight kind, so an insight can point somewhere specific without the client
 * having to know why. Unknown verbs return null and the card simply omits the
 * button — better than a link that goes nowhere. */
export function actionRoute(action: Record<string, unknown>): { to: string; label: string } | null {
  const verb = typeof action?.action === "string" ? action.action : null;
  switch (verb) {
    case "open_cashflow_calendar":
      return { to: "/cashflow", label: "Open cash flow" };
    case "review_category":
      return action.category_id
        ? { to: `/transactions?category_id=${action.category_id}`, label: "See transactions" }
        : { to: "/transactions", label: "See transactions" };
    case "review_transaction":
      return action.transaction_id
        ? { to: `/transactions?tx=${action.transaction_id}`, label: "See transaction" }
        : null;
    case "create_budget":
      return { to: "/budgets?add=1", label: "Create a budget" };
    case "create_goal":
      return { to: "/goals?add=1", label: "Create a goal" };
    case "open_debt_planner":
      return { to: "/debt", label: "Open debt planner" };
    case "open_recurring":
      return { to: "/recurring", label: "Review subscriptions" };
    case "open_account":
      return { to: "/accounts", label: "Open accounts" };
    case "open_bills":
      return { to: "/bills", label: "Open bills" };
    case "open_income":
      return { to: "/income", label: "Open income" };
    default:
      return null;
  }
}

/** Human labels for the evidence keys we know about.
 *
 * Only known keys are rendered. Dumping an opaque dict at the user would be
 * worse than showing nothing — the point of evidence is that it's readable. */
export const EVIDENCE_LABELS: Record<string, string> = {
  limit_minor: "Budget limit",
  spent_minor: "Spent",
  over_minor: "Over by",
  current_minor: "This month",
  previous_minor: "Last month",
  amount_minor: "Amount",
  total_minor: "Total",
  annual_total_minor: "Yearly cost",
  lowest_balance_minor: "Lowest balance",
  suggested_target_minor: "Suggested target",
  safe_to_spend_minor: "Free to spend",
  committed_minor: "Already committed",
  count: "Occurrences",
  accounts: "Accounts",
  days_until_due: "Days until due",
  committed_ratio: "Share of income",
  next_payday_on: "Next payday",
};

/** Keys whose values are money in minor units, so the card formats them. */
export const MONEY_EVIDENCE_KEYS = new Set(
  Object.keys(EVIDENCE_LABELS).filter((k) => k.endsWith("_minor")),
);
