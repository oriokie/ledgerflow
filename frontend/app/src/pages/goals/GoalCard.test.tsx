import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SavingsGoal } from "../../api/types";

const mutateAsync = vi.fn().mockResolvedValue({});
vi.mock("../../hooks/useGoals", () => ({
  useContributeToGoal: () => ({ mutateAsync, isPending: false }),
  useGoalContributions: () => ({ data: [], isLoading: false }),
}));

import { GoalCard } from "./GoalCard";

function goal(over: Partial<SavingsGoal> = {}): SavingsGoal {
  const target = over.target_minor ?? 10000;
  const saved = over.saved_minor ?? 6000;
  return {
    id: "g1",
    name: "Japan trip",
    currency: "USD",
    target_minor: target,
    target_date: null,
    tracking: "manual",
    linked_account_id: null,
    status: "active",
    notes: "",
    saved_minor: saved,
    remaining_minor: Math.max(0, target - saved),
    percent: target > 0 ? Math.min(100, (saved / target) * 100) : 0,
    is_met: saved >= target,
    required_monthly_minor: null,
    kind: "custom",
    priority: 3,
    planned_monthly_minor: null,
    auto_contribute_enabled: false,
    auto_contribute_minor: null,
    auto_contribute_day: null,
    ...over,
  };
}

beforeEach(() => mutateAsync.mockClear());

describe("GoalCard", () => {
  it("shows the progress ring and the next-milestone nudge", () => {
    render(<GoalCard goal={goal()} onArchive={() => {}} />);
    expect(screen.getByRole("img", { name: /60% saved/i })).toBeInTheDocument();
    expect(screen.getByText(/\$15\.00 to 75%/)).toBeInTheDocument();
  });

  it("contributes the chip amount with one tap", async () => {
    render(<GoalCard goal={goal()} onArchive={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "+$50.00" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith({ goalId: "g1", amountMinor: 5000 }));
  });

  it("contributes a custom amount in minor units", async () => {
    render(<GoalCard goal={goal()} onArchive={() => {}} />);
    fireEvent.change(screen.getByLabelText(/contribute to japan trip/i), { target: { value: "12.50" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith({ goalId: "g1", amountMinor: 1250 }));
  });

  it("celebrates a reached goal and hides contribution inputs", () => {
    render(<GoalCard goal={goal({ saved_minor: 10000 })} onArchive={() => {}} />);
    expect(screen.getByText("Goal reached!")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^\+\$/ })).not.toBeInTheDocument();
  });
});
