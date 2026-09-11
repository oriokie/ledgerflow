import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { BudgetLineStatus, BudgetStatus } from "../../api/types";
import { BudgetSummary } from "./BudgetSummary";

const line: BudgetLineStatus = {
  line_id: "l1",
  category_id: "c1",
  category_name: "Groceries",
  limit_minor: 40000,
  carried_minor: 0,
  effective_limit_minor: 40000,
  actual_minor: 10000,
  remaining_minor: 30000,
  percent_used: 25,
  over_budget: false,
  rollover: false,
};

function status(over: Partial<BudgetStatus> = {}): BudgetStatus {
  return {
    budget_id: "b1",
    as_of: "2026-01-16",
    period_start: "2026-01-01",
    period_end: "2026-02-01",
    lines: [line],
    ...over,
  };
}

describe("BudgetSummary assignment", () => {
  it("shows what’s left to budget against expected income", () => {
    render(
      <MemoryRouter>
        <BudgetSummary
          currency="USD"
          status={status({
            assignment: {
              income_minor: 100000,
              income_known: true,
              assigned_minor: 40000,
              unassigned_minor: 60000,
              overspent_minor: 0,
            },
          })}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("Left to budget")).toBeInTheDocument();
    expect(screen.getByText("Expected income")).toBeInTheDocument();
  });

  it("names over-budgeting when limits exceed income", () => {
    render(
      <MemoryRouter>
        <BudgetSummary
          currency="USD"
          status={status({
            assignment: {
              income_minor: 20000,
              income_known: true,
              assigned_minor: 40000,
              unassigned_minor: -20000,
              overspent_minor: 0,
            },
          })}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("Over-budgeted by")).toBeInTheDocument();
  });

  it("asks for income instead of inventing a zero", () => {
    render(
      <MemoryRouter>
        <BudgetSummary
          currency="USD"
          status={status({
            assignment: {
              income_minor: 0,
              income_known: false,
              assigned_minor: 40000,
              unassigned_minor: null,
              overspent_minor: 0,
            },
          })}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /add income/i })).toHaveAttribute("href", "/income");
    expect(screen.getByText(/left to budget against/i)).toBeInTheDocument();
  });
});
