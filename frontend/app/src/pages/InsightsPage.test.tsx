import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Anomaly, CategorizationSuggestion, HealthScore, Recommendation } from "../api/types";

const health: HealthScore = {
  score: 72,
  band: "good",
  // Every component below is measured, so the score rests on the full weight.
  coverage: 1,
  provider: "x",
  version: "1",
  components: [
    { name: "Savings rate", score: 90, weight: 0.3, detail: "Keeping 22% of income." },
    { name: "Emergency fund", score: 40, weight: 0.3, detail: "2.4 months of essentials covered." },
  ],
};
const recommendations: Recommendation[] = [
  {
    kind: "budget_rebalance",
    title: "Groceries is over by 62.00",
    body: "Dining out has 80.00 unspent.",
    severity: "attention",
    action: { action: "budget_rebalance" },
  },
];
const anomalies: Anomaly[] = [
  { transaction_id: "t1", kind: "amount_spike", severity: 0.8, explanation: "Utilities: 3x the usual." },
];
const suggestions: CategorizationSuggestion[] = [
  {
    id: "s1",
    transaction_id: "t2",
    suggested_category_id: "c1",
    confidence: 0.9,
    status: "pending",
    provider: "p",
    provider_kind: "rule",
    provider_version: "1",
    rationale: "Payee matches groceries.",
    decided_at: null,
    created_at: "2026-01-01",
  },
];

vi.mock("../hooks/useIntelligence", () => ({
  useCashRunway: () => ({ data: undefined }),
  useMilestones: () => ({ data: [] }),
  useHealthScore: () => ({ data: health }),
  useRecommendations: () => ({ data: recommendations }),
  useAnomalies: () => ({ data: anomalies }),
  useSuggestions: () => ({ data: suggestions }),
  useDecideSuggestion: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("../hooks/useFinance", () => ({
  useCategories: () => ({ data: [{ id: "c1", name: "Groceries", kind: "expense", path: "Groceries", depth: 0, parent_id: null }] }),
}));
const aiEnabled = { value: true };
vi.mock("../hooks/useEntitlements", () => ({
  useAiEnabled: () => ({ aiEnabled: aiEnabled.value, isLoading: false }),
}));

import { InsightsPage } from "./InsightsPage";

describe("InsightsPage", () => {
  it("shows an upgrade prompt when the plan lacks AI insights", () => {
    aiEnabled.value = false;
    render(
      <MemoryRouter>
        <InsightsPage />
      </MemoryRouter>,
    );
    expect(screen.getByText(/premium feature/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /see plans/i })).toHaveAttribute("href", "/billing");
    aiEnabled.value = true;
  });

  it("leads with a conversational check-in and actionable guidance", () => {
    render(
      <MemoryRouter>
        <InsightsPage />
      </MemoryRouter>,
    );

    // Greeting
    expect(screen.getByText("Your money check-in")).toBeInTheDocument();
    expect(screen.getAllByText(/good shape/i).length).toBeGreaterThan(0);

    // Guidance with a real next step
    expect(screen.getByText("Groceries is over by 62.00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open budgets" })).toBeInTheDocument();

    // Health, human-framed
    expect(screen.getByText("Your financial health")).toBeInTheDocument();
    expect(screen.getByText("Good")).toBeInTheDocument();

    // Worth a look, plain language
    expect(screen.getByText("A charge that's higher than usual")).toBeInTheDocument();

    // Conversational categorization
    expect(screen.getByText(/want to file it there/i)).toBeInTheDocument();
    expect(screen.getByText(/very sure/i)).toBeInTheDocument();
  });
});
