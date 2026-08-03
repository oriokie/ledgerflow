import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { BorrowingCost } from "../../api/types";
import { BorrowingCostCard } from "./BorrowingCostCard";

const COST: BorrowingCost = {
  currency: "USD",
  annual_interest_minor: 240_000,
  annual_fees_minor: 15_900,
  annual_total_minor: 255_900,
  monthly_interest_minor: 20_000,
  monthly_fees_minor: 500,
  fee_share: 6.2,
  priced_count: 2,
  debt_count: 2,
};

describe("BorrowingCostCard", () => {
  it("splits interest from fees, because they behave differently", () => {
    // Interest falls as the balance does; an annual fee doesn't.
    render(<BorrowingCostCard cost={COST} />);
    expect(screen.getByText("Interest")).toBeInTheDocument();
    expect(screen.getByText("Fees")).toBeInTheDocument();
  });

  it("stays quiet when fees are a small share", () => {
    render(<BorrowingCostCard cost={COST} />);
    expect(screen.queryByText(/won't reduce that portion/i)).not.toBeInTheDocument();
  });

  it("warns when much of the cost is fees paying down won't touch", () => {
    render(<BorrowingCostCard cost={{ ...COST, fee_share: 62.0 }} />);
    expect(screen.getByText(/62% of what you pay is fees/i)).toBeInTheDocument();
    expect(screen.getByText(/won't reduce that portion/i)).toBeInTheDocument();
  });

  it("does not report a cost of zero when no terms were recorded", () => {
    // Every input here is contract metadata — none of it is derivable from the
    // ledger. With nothing recorded the card used to render a confident
    // "Cost of borrowing this year: 0.00", which tells someone carrying a
    // balance that carrying it is free. That is the most misleading statement
    // the page could make, and it was the default for any untermed debt.
    render(<BorrowingCostCard cost={{ ...COST, priced_count: 0 }} />);

    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
    expect(screen.queryByText("Interest")).not.toBeInTheDocument();
    expect(screen.getByText(/not yet known/i)).toBeInTheDocument();
    expect(screen.getByText(/come from each debt's terms, not from your transactions/i)).toBeInTheDocument();
  });

  it("offers the fix rather than only reporting the gap", async () => {
    const onAddTerms = vi.fn();
    render(<BorrowingCostCard cost={{ ...COST, priced_count: 0 }} onAddTerms={onAddTerms} />);
    await userEvent.click(screen.getByRole("button", { name: /add terms/i }));
    expect(onAddTerms).toHaveBeenCalledOnce();
  });

  it("calls a partial total a floor, not the figure", () => {
    render(<BorrowingCostCard cost={{ ...COST, priced_count: 1, debt_count: 3 }} />);
    expect(screen.getByText(/at least this much/i)).toBeInTheDocument();
    expect(screen.getByText(/terms recorded for 1 of 3 debts/i)).toBeInTheDocument();
  });
});