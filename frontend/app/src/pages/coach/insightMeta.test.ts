import { describe, expect, it } from "vitest";
import type { InsightKind, InsightSeverity } from "../../api/types";
import {
  actionRoute,
  EVIDENCE_LABELS,
  INSIGHT_ICONS,
  INSIGHT_KIND_LABELS,
  MONEY_EVIDENCE_KEYS,
  SEVERITY_LABELS,
} from "./insightMeta";

const ALL_KINDS: InsightKind[] = [
  "spending_anomaly",
  "overspending",
  "budget_recommendation",
  "savings_opportunity",
  "duplicate_transaction",
  "large_purchase",
  "merchant_change",
  "salary_change",
  "cashflow_risk",
  "subscription_review",
  "goal_recommendation",
  "debt_recommendation",
  "health_improvement",
];

const ALL_SEVERITIES: InsightSeverity[] = ["critical", "warning", "opportunity", "info"];

describe("insight metadata completeness", () => {
  it("has an icon and a label for every backend insight kind", () => {
    // A kind added server-side but missed here would render as a blank card.
    for (const kind of ALL_KINDS) {
      expect(INSIGHT_ICONS[kind], `missing icon for ${kind}`).toBeDefined();
      expect(INSIGHT_KIND_LABELS[kind], `missing label for ${kind}`).toBeTruthy();
    }
  });

  it("has a label for every severity", () => {
    for (const severity of ALL_SEVERITIES) {
      expect(SEVERITY_LABELS[severity]).toBeTruthy();
    }
  });

  it("treats every _minor evidence key as money", () => {
    // A money key not in this set would render as a raw integer like "35000".
    for (const key of Object.keys(EVIDENCE_LABELS)) {
      if (key.endsWith("_minor")) expect(MONEY_EVIDENCE_KEYS.has(key)).toBe(true);
    }
  });

  it("does not treat count-like keys as money", () => {
    expect(MONEY_EVIDENCE_KEYS.has("count")).toBe(false);
    expect(MONEY_EVIDENCE_KEYS.has("accounts")).toBe(false);
  });
});

describe("actionRoute", () => {
  it("maps known verbs to real destinations", () => {
    expect(actionRoute({ action: "open_cashflow_calendar" })?.to).toBe("/cashflow");
    expect(actionRoute({ action: "create_budget" })?.to).toBe("/budgets?add=1");
    expect(actionRoute({ action: "create_goal" })?.to).toBe("/goals?add=1");
    expect(actionRoute({ action: "open_recurring" })?.to).toBe("/recurring");
  });

  it("carries the id through when the verb has a target", () => {
    expect(actionRoute({ action: "review_category", category_id: "c9" })?.to).toBe(
      "/transactions?category_id=c9",
    );
    expect(actionRoute({ action: "review_transaction", transaction_id: "t9" })?.to).toBe(
      "/transactions?tx=t9",
    );
  });

  it("degrades to a general destination when the id is missing", () => {
    expect(actionRoute({ action: "review_category" })?.to).toBe("/transactions");
  });

  it("returns null rather than a link that goes nowhere", () => {
    expect(actionRoute({ action: "review_transaction" })).toBeNull();
    expect(actionRoute({ action: "unknown_verb" })).toBeNull();
    expect(actionRoute({})).toBeNull();
  });
});
