import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { DebtSummary } from "../../api/types";
import { DebtSummaryCard } from "./DebtSummaryCard";

const SUMMARY: DebtSummary = {
  currency: "USD",
  total_balance_minor: 500_000,
  total_minimum_minor: 20_000,
  total_monthly_interest_minor: 8_000,
  annual_interest_minor: 96_000,
  debt_count: 2,
  weighted_apr: 19.9,
  highest_apr_name: "Card",
  highest_apr: 19.9,
  unplannable_count: 0,
  growing_count: 0,
  priced_count: 2,
  alerts: [],
  recommendation: null,
};

/** A real balance with no terms recorded against any of it. */
const UNPRICED: DebtSummary = {
  ...SUMMARY,
  total_minimum_minor: 0,
  total_monthly_interest_minor: 0,
  annual_interest_minor: 0,
  weighted_apr: 0,
  highest_apr_name: null,
  highest_apr: null,
  unplannable_count: 2,
  priced_count: 0,
};

describe("DebtSummaryCard", () => {
  it("shows the derived figures when the terms behind them exist", () => {
    render(<DebtSummaryCard summary={SUMMARY} />);
    expect(screen.getByText("Monthly minimums")).toBeInTheDocument();
    expect(screen.getByText("Average rate")).toBeInTheDocument();
    expect(screen.getByText("19.9%")).toBeInTheDocument();
    expect(screen.getByText(/interest is costing about/i)).toBeInTheDocument();
  });

  it("never renders a zero it did not measure", () => {
    // The defect this card was rebuilt around. Every input to the rate and
    // interest figures is contract metadata; with none recorded they compute to
    // zero, and the old card printed "Average rate 0%" and "Monthly minimums
    // 0.00" in the same type as the ledger total above them. A zero is a
    // finding. Missing data is not, and must not borrow a finding's authority.
    render(<DebtSummaryCard summary={UNPRICED} />);

    expect(screen.queryByText("Average rate")).not.toBeInTheDocument();
    expect(screen.queryByText("Monthly minimums")).not.toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.queryByText(/interest is costing about/i)).not.toBeInTheDocument();

    // The balance itself is a ledger fact and still leads the card.
    expect(screen.getByText("Total owed")).toBeInTheDocument();
    expect(screen.getByText(/no interest rates or minimum payments are recorded/i)).toBeInTheDocument();
  });

  it("does not repeat the missing-terms alert it has already explained", () => {
    // The backend emits "N debts missing terms" whenever any debt lacks them.
    // With none priced the card states that in full, so keeping the alert put
    // the same fact on screen twice, 60px apart.
    const alert = {
      severity: "info" as const,
      title: "1 debt missing terms",
      body: "Add the interest rate and minimum payment to include it in your payoff plan.",
      account_id: null,
    };
    const { unmount } = render(<DebtSummaryCard summary={{ ...UNPRICED, alerts: [alert] }} />);
    expect(screen.queryByText("1 debt missing terms")).not.toBeInTheDocument();
    unmount();

    // It still earns its place when only some terms are missing: there the
    // card's note is an aside, and the alert names the cost to the plan.
    render(<DebtSummaryCard summary={{ ...SUMMARY, priced_count: 1, alerts: [alert] }} />);
    expect(screen.getByText("1 debt missing terms")).toBeInTheDocument();
  });

  it("offers the fix rather than only reporting the gap", async () => {
    const onAddTerms = vi.fn();
    render(<DebtSummaryCard summary={UNPRICED} onAddTerms={onAddTerms} />);
    await userEvent.click(screen.getByRole("button", { name: /add terms/i }));
    expect(onAddTerms).toHaveBeenCalledOnce();
  });

  it("says what a partial figure covers instead of passing it off as complete", () => {
    // Terms on one of two debts: the figures are real and they describe half
    // the balance. Suppressing them would throw away a true measurement;
    // showing them bare would overstate what was measured.
    render(
      <DebtSummaryCard summary={{ ...SUMMARY, priced_count: 1, unplannable_count: 1 }} />,
    );
    expect(screen.getByText("Average rate")).toBeInTheDocument();
    expect(screen.getByText(/terms recorded for 1 of 2 debts/i)).toBeInTheDocument();
    expect(screen.getByText(/on the debts with terms recorded/i)).toBeInTheDocument();
  });

  it("distinguishes a missing minimum from a missing rate", () => {
    // Rates recorded, minimums not. The rate figure stands; the minimums
    // figure goes, because nothing was entered to total up.
    render(
      <DebtSummaryCard summary={{ ...SUMMARY, unplannable_count: 2, total_minimum_minor: 0 }} />,
    );
    expect(screen.getByText("Average rate")).toBeInTheDocument();
    expect(screen.queryByText("Monthly minimums")).not.toBeInTheDocument();
    expect(screen.getByText(/no minimum payments recorded/i)).toBeInTheDocument();
  });
});
