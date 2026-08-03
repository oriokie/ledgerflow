import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ConsolidationResult, DebtView } from "../../api/types";

const simulateConsolidation = vi.fn();
vi.mock("../../api/debt", () => ({
  debtApi: { simulateConsolidation: (...a: unknown[]) => simulateConsolidation(...a) },
}));

import { ConsolidationModal } from "./ConsolidationModal";

function debt(id: string, name: string, apr: number, hasTerms = true): DebtView {
  return {
    account_id: id,
    name,
    currency: "USD",
    debt_kind: "credit_card",
    balance_minor: 500_000,
    apr,
    minimum_payment_minor: hasTerms ? 20_000 : 0,
    payment_day: null,
    monthly_interest_minor: 10_000,
    minimum_covers_interest: true,
    original_principal_minor: null,
    percent_repaid: null,
    include_in_payoff: true,
    has_terms: hasTerms,
  };
}

const DEBTS = [debt("a", "Card A", 24), debt("b", "Card B", 19)];

const COSTLIER: ConsolidationResult = {
  debt_count: 2,
  combined_balance_minor: 1_000_000,
  current_total_cost_minor: 1_200_000,
  new_total_cost_minor: 1_350_000,
  lifetime_saving_minor: -150_000,
  current_months: 30,
  new_months: 60,
  months_saved: -30,
  current_monthly_minor: 40_000,
  new_monthly_minor: 22_000,
  current_weighted_apr: 21.5,
  new_apr: 11.0,
  is_worthwhile: false,
};

beforeEach(() => vi.clearAllMocks());

describe("ConsolidationModal", () => {
  it("requires at least two debts before it can compare", () => {
    render(<ConsolidationModal open debts={[DEBTS[0]]} onClose={vi.fn()} />);
    expect(screen.getByText(/at least two debts/i)).toBeInTheDocument();
  });

  it("only offers debts that have terms recorded", () => {
    // Modelling one without a rate would compare against figures we don't have.
    render(
      <ConsolidationModal
        open
        debts={[...DEBTS, debt("c", "No terms card", 0, false)]}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/Card A/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/No terms card/)).not.toBeInTheDocument();
  });

  it("keeps the compare button disabled until two are picked", async () => {
    const user = userEvent.setup();
    render(<ConsolidationModal open debts={DEBTS} onClose={vi.fn()} />);
    const compare = screen.getByRole("button", { name: /^compare$/i });
    expect(compare).toBeDisabled();

    await user.click(screen.getByLabelText(/Card A/));
    expect(screen.getByText(/combining one debt isn't consolidation/i)).toBeInTheDocument();
    expect(compare).toBeDisabled();

    await user.click(screen.getByLabelText(/Card B/));
    expect(compare).toBeEnabled();
  });

  it("names the trap when a lower payment costs more overall", async () => {
    const user = userEvent.setup();
    simulateConsolidation.mockResolvedValue(COSTLIER);
    render(<ConsolidationModal open debts={DEBTS} onClose={vi.fn()} />);

    await user.click(screen.getByLabelText(/Card A/));
    await user.click(screen.getByLabelText(/Card B/));
    await user.type(screen.getByLabelText(/loan rate/i), "11");
    await user.type(screen.getByLabelText(/monthly payment/i), "220");
    await user.click(screen.getByRole("button", { name: /^compare$/i }));

    // The judgement is on lifetime cost, and the reason is stated.
    expect(await screen.findByText(/costs about .* more overall/i)).toBeInTheDocument();
    expect(
      screen.getByText(/smaller monthly payment over a longer term can cost more/i),
    ).toBeInTheDocument();
  });

  it("shows monthly and total side by side so they can't be confused", async () => {
    const user = userEvent.setup();
    simulateConsolidation.mockResolvedValue(COSTLIER);
    render(<ConsolidationModal open debts={DEBTS} onClose={vi.fn()} />);

    await user.click(screen.getByLabelText(/Card A/));
    await user.click(screen.getByLabelText(/Card B/));
    await user.type(screen.getByLabelText(/loan rate/i), "11");
    await user.type(screen.getByLabelText(/monthly payment/i), "220");
    await user.click(screen.getByRole("button", { name: /^compare$/i }));

    expect(await screen.findByText("Monthly now")).toBeInTheDocument();
    expect(screen.getByText("Monthly after")).toBeInTheDocument();
    expect(screen.getByText("Total now")).toBeInTheDocument();
    expect(screen.getByText("Total after")).toBeInTheDocument();
  });
});
