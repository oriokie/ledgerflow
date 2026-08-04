import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { BaselineResponse, Projection, Scenario } from "../api/projections";

function projection(overrides: Partial<Projection> = {}): Projection {
  return {
    currency: "KES",
    as_of: "2026-08-01",
    months: 12,
    summary: {
      opening_net_worth_minor: 1_000_000,
      closing_net_worth_minor: 2_200_000,
      lowest_liquid_minor: 400_000,
      lowest_liquid_month: 3,
      first_negative_month: null,
      first_negative_on: null,
      debt_free_month: 8,
      total_interest_paid_minor: 45_000,
    },
    points: Array.from({ length: 12 }, (_, i) => ({
      month: i + 1,
      on: `2026-${String((i % 12) + 1).padStart(2, "0")}-01`,
      income_minor: 500_000,
      expenses_minor: 300_000,
      debt_payments_minor: 20_000,
      net_cashflow_minor: 180_000,
      liquid_minor: 400_000 + i * 100_000,
      investment_minor: 250_000,
      other_assets_minor: 0,
      debt_balance_minor: Math.max(0, 200_000 - i * 25_000),
      net_worth_minor: 1_000_000 + i * 100_000,
      events: [],
    })),
    assumptions: ["Inflation 5.00% a year, applied to living costs."],
    warnings: [],
    ...overrides,
  };
}

const baseline: BaselineResponse = {
  position: {
    currency: "KES",
    as_of: "2026-08-01",
    liquid_minor: 400_000,
    investment_minor: 250_000,
    other_assets_minor: 0,
    monthly_net_income_minor: 500_000,
    monthly_expenses_minor: 300_000,
    net_worth_minor: 1_000_000,
    debts: [],
  },
  projection: projection(),
};

const scenarios: Scenario[] = [
  {
    id: "s1",
    name: "Buy a house in 2028",
    description: "",
    status: "draft",
    visibility: "private",
    horizon_months: 120,
    assumption_set_id: null,
    duplicated_from_id: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    events: [],
  },
];

const run = vi.fn();

vi.mock("../api/projections", () => ({
  projectionsApi: {
    baseline: () => Promise.resolve(baseline),
    listScenarios: () => Promise.resolve({ results: scenarios }),
    eventCatalogue: () =>
      Promise.resolve({
        results: [
          {
            kind: "salary_increase",
            label: "A pay rise",
            params: [
              { name: "monthly_gross_increase_minor", required: true, type: "int", default: 0 },
            ],
          },
        ],
      }),
    run: (...args: unknown[]) => {
      run(...args);
      return Promise.resolve({
        scenario_id: "s1",
        scenario_name: "Buy a house in 2028",
        baseline: projection(),
        scenario: projection({
          summary: { ...projection().summary, closing_net_worth_minor: 3_000_000 },
        }),
        delta: { net_worth_minor: 800_000, trough_minor: -50_000 },
        notes: ["The baseline is this same position with the scenario's events removed."],
      });
    },
  },
}));

import { ProjectionsPage } from "./ProjectionsPage";

const renderPage = () =>
  render(
    <MemoryRouter>
      <ProjectionsPage />
    </MemoryRouter>,
  );

describe("ProjectionsPage", () => {
  it("leads with the trough rather than only the closing balance", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Lowest your cash gets")).toBeInTheDocument());
    expect(screen.getByText("Net worth at the end")).toBeInTheDocument();
    expect(screen.getByText("Debt free")).toBeInTheDocument();
  });

  it("lists the workspace's scenarios", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByText("Buy a house in 2028")).toBeInTheDocument(),
    );
  });

  it("shows what the selected scenario changes, in both directions", async () => {
    renderPage();
    await waitFor(() => expect(run).toHaveBeenCalledWith("s1"));
    // The delta banner names the scenario and reports both the end state and
    // the trough — a scenario that improves the end while deepening the dip is
    // the case a single number would hide.
    await waitFor(() =>
      expect(screen.getByText(/ends .* different/)).toBeInTheDocument(),
    );
  });

  it("always states its assumptions", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("What this assumes")).toBeInTheDocument());
    expect(
      screen.getByText(/Inflation 5.00% a year/),
    ).toBeInTheDocument();
  });

  it("offers every horizon out to forty years", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("40 years")).toBeInTheDocument());
    expect(screen.getByText("5 years")).toBeInTheDocument();
  });
});
