import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DebtView, RefinanceResult } from "../../api/types";

const mutateAsync = vi.fn();
vi.mock("../../hooks/useDebt", () => ({
  useSimulateRefinance: () => ({ mutateAsync }),
}));

import { RefinanceModal } from "./RefinanceModal";

const DEBT: DebtView = {
  account_id: "d1",
  name: "Car loan",
  currency: "USD",
  debt_kind: "vehicle loan",
  balance_minor: 2_000_000,
  apr: 18,
  minimum_payment_minor: 50_000,
  payment_day: 15,
  monthly_interest_minor: 30_000,
  minimum_covers_interest: true,
  original_principal_minor: null,
  percent_repaid: null,
  include_in_payoff: true,
  has_terms: true,
};

const WORTHWHILE: RefinanceResult = {
  current_total_cost_minor: 2_800_000,
  new_total_cost_minor: 2_400_000,
  lifetime_saving_minor: 400_000,
  current_months: 56,
  new_months: 48,
  months_saved: 8,
  current_monthly_minor: 50_000,
  new_monthly_minor: 50_000,
  breakeven_month: 14,
  closing_costs_minor: 50_000,
  is_worthwhile: true,
};

beforeEach(() => vi.clearAllMocks());

async function submit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/new rate/i), "6.9");
  await user.click(screen.getByRole("button", { name: /^compare$/i }));
}

describe("RefinanceModal", () => {
  it("states that nothing is changed", () => {
    // "Record a refinance" could reasonably be read as applying one.
    render(<RefinanceModal debt={DEBT} onClose={vi.fn()} />);
    expect(screen.getByText(/nothing about your existing debt changes/i)).toBeInTheDocument();
  });

  it("shows the current rate for comparison", () => {
    render(<RefinanceModal debt={DEBT} onClose={vi.fn()} />);
    expect(screen.getByText(/you currently pay 18%/i)).toBeInTheDocument();
  });

  it("leads the result with breakeven, not the lifetime saving", async () => {
    const user = userEvent.setup();
    mutateAsync.mockResolvedValue(WORTHWHILE);
    render(<RefinanceModal debt={DEBT} onClose={vi.fn()} />);
    await submit(user);

    // A saving arriving after you've repaid is not a saving.
    expect(await screen.findByText("Breakeven")).toBeInTheDocument();
    expect(screen.getByText("Month 14")).toBeInTheDocument();
  });

  it("warns when a saving never pays back the fees", async () => {
    const user = userEvent.setup();
    mutateAsync.mockResolvedValue({
      ...WORTHWHILE,
      breakeven_month: null,
      is_worthwhile: false,
      lifetime_saving_minor: 20_000,
    });
    render(<RefinanceModal debt={DEBT} onClose={vi.fn()} />);
    await submit(user);

    expect(await screen.findByText(/never quite pays back the fees/i)).toBeInTheDocument();
    expect(screen.getByText("Never")).toBeInTheDocument();
  });

  it("says plainly when the deal costs more", async () => {
    const user = userEvent.setup();
    mutateAsync.mockResolvedValue({
      ...WORTHWHILE,
      lifetime_saving_minor: -150_000,
      is_worthwhile: false,
      breakeven_month: null,
    });
    render(<RefinanceModal debt={DEBT} onClose={vi.fn()} />);
    await submit(user);

    expect(await screen.findByText(/would cost about .* more overall/i)).toBeInTheDocument();
  });

  it("tells the user when switching would cost them", async () => {
    const user = userEvent.setup();
    mutateAsync.mockResolvedValue(WORTHWHILE);
    render(<RefinanceModal debt={DEBT} onClose={vi.fn()} />);
    await submit(user);

    expect(
      await screen.findByText(/repay or move before month 14, switching costs you money/i),
    ).toBeInTheDocument();
  });

  it("converts entered amounts to minor units", async () => {
    const user = userEvent.setup();
    mutateAsync.mockResolvedValue(WORTHWHILE);
    render(<RefinanceModal debt={DEBT} onClose={vi.fn()} />);
    await user.type(screen.getByLabelText(/new rate/i), "6.9");
    await user.type(screen.getByLabelText(/fees and closing costs/i), "500");
    await user.click(screen.getByRole("button", { name: /^compare$/i }));

    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        payload: expect.objectContaining({ closing_costs_minor: 50_000 }),
      }),
    );
  });

  it("rejects an implausible rate before calling the server", async () => {
    const user = userEvent.setup();
    render(<RefinanceModal debt={DEBT} onClose={vi.fn()} />);
    await user.type(screen.getByLabelText(/new rate/i), "690");
    await user.click(screen.getByRole("button", { name: /^compare$/i }));

    expect(await screen.findByText(/enter it as a percentage/i)).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
  });
});
