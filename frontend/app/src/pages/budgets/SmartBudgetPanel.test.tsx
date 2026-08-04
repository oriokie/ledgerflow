import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SmartBudgetProposal } from "../../api/types";

const suggestBudget = vi.fn();
const applySuggestedBudget = vi.fn();
vi.mock("../../api/budgeting", () => ({
  budgetingApi: {
    suggestBudget: (...a: unknown[]) => suggestBudget(...a),
    applySuggestedBudget: (...a: unknown[]) => applySuggestedBudget(...a),
  },
}));

import { SmartBudgetPanel } from "./SmartBudgetPanel";

const PROPOSAL: SmartBudgetProposal = {
  currency: "USD",
  as_of: "2026-08-04",
  months_considered: 3,
  income_minor: 500_000,
  income_known: true,
  debt_minimums_minor: 20_000,
  savings_target_minor: 100_000,
  envelope_minor: 380_000,
  total_minor: 350_000,
  left_over_minor: 30_000,
  trim_factor: 0.82,
  deficit: false,
  lines: [
    {
      category_id: "c1",
      category_name: "Groceries",
      limit_minor: 120_000,
      floor_minor: 0,
      history_minor: 140_000,
      observed_months: [138_000, 140_000, 143_000],
      rationale: "Median of your last 3 months; trimmed 18% to fund your savings goals",
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  suggestBudget.mockResolvedValue(PROPOSAL);
});

const renderPanel = (props: Partial<Parameters<typeof SmartBudgetPanel>[0]> = {}) =>
  render(<SmartBudgetPanel onCreated={vi.fn()} onCancel={vi.fn()} {...props} />);

describe("SmartBudgetPanel", () => {
  it("shows the envelope math before the lines", async () => {
    renderPanel();
    expect(await screen.findByText("Monthly income")).toBeInTheDocument();
    expect(screen.getByText("Savings goals")).toBeInTheDocument();
    expect(screen.getByText("Left to budget")).toBeInTheDocument();
  });

  it("every line carries its reasoning", async () => {
    // A suggested number a person cannot interrogate is a number they will
    // not trust — and rightly so.
    renderPanel();
    expect(await screen.findByText(/median of your last 3 months/i)).toBeInTheDocument();
  });

  it("says when flexible spending was trimmed for the goals", async () => {
    renderPanel();
    expect(
      await screen.findByText(/flexible categories are trimmed 18%/i),
    ).toBeInTheDocument();
  });

  it("a deficit is stated plainly, never papered over", async () => {
    suggestBudget.mockResolvedValue({ ...PROPOSAL, deficit: true });
    renderPanel();
    expect(await screen.findByText(/commitments alone exceed your income/i)).toBeInTheDocument();
  });

  it("applies only on the explicit button, then hands over the new budget", async () => {
    applySuggestedBudget.mockResolvedValue({ budget: { id: "b9" }, proposal: PROPOSAL });
    const onCreated = vi.fn();
    const user = userEvent.setup();
    renderPanel({ onCreated });
    await screen.findByText("Monthly income");
    expect(applySuggestedBudget).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /use this budget/i }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("b9"));
  });

  it("an empty workspace gets the explanation, not an error screen", async () => {
    const { ApiError } = await import("../../api/client");
    suggestBudget.mockRejectedValue(
      new ApiError(404, { detail: "Not enough categorised spending yet." }),
    );
    renderPanel();
    expect(await screen.findByText(/not enough categorised spending/i)).toBeInTheDocument();
  });
});
