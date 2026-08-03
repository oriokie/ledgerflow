import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { SavingsGoal } from "../api/types";

const goals: SavingsGoal[] = [
  {
    id: "g1",
    name: "Emergency fund",
    currency: "USD",
    target_minor: 100000,
    target_date: null,
    tracking: "manual",
    linked_account_id: null,
    status: "active",
    notes: "",
    saved_minor: 60000,
    remaining_minor: 40000,
    percent: 60,
    is_met: false,
    required_monthly_minor: null,
    kind: "custom",
    priority: 3,
    planned_monthly_minor: null,
    auto_contribute_enabled: false,
    auto_contribute_minor: null,
    auto_contribute_day: null,
  },
  {
    id: "g2",
    name: "New laptop",
    currency: "USD",
    target_minor: 20000,
    target_date: null,
    tracking: "manual",
    linked_account_id: null,
    status: "active",
    notes: "",
    saved_minor: 20000,
    remaining_minor: 0,
    percent: 100,
    is_met: true,
    required_monthly_minor: null,
    kind: "custom",
    priority: 3,
    planned_monthly_minor: null,
    auto_contribute_enabled: false,
    auto_contribute_minor: null,
    auto_contribute_day: null,
  },
];

vi.mock("../hooks/useGoals", () => ({
  useGoals: () => ({ data: goals, isLoading: false }),
  useArchiveGoal: () => ({ mutate: vi.fn() }),
  useContributeToGoal: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useGoalContributions: () => ({ data: [], isLoading: false }),
  useGoalForecasts: () => ({ data: [] }),
  useGoalRecommendations: () => ({ data: [] }),
}));

import { GoalsPage } from "./GoalsPage";

describe("GoalsPage", () => {
  it("shows the summary and a card per goal, celebrating the achieved one", () => {
    render(
      <MemoryRouter>
        <GoalsPage />
      </MemoryRouter>,
    );

    expect(screen.getByText("Saved across goals")).toBeInTheDocument();
    expect(screen.getByText(/1 of 2/)).toBeInTheDocument(); // achieved count

    expect(screen.getByText("Emergency fund")).toBeInTheDocument();
    expect(screen.getByText("New laptop")).toBeInTheDocument();
    expect(screen.getByText("Goal reached!")).toBeInTheDocument();

    // A ring per goal + the summary meter
    expect(screen.getAllByRole("img", { name: /saved/i }).length).toBe(2);
  });
});
