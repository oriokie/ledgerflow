import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PortfolioSummary } from "../../api/types";
import { PortfolioSummaryCard } from "./PortfolioSummaryCard";

const SUMMARY: PortfolioSummary = {
  currency: "USD",
  cost_basis_minor: 500_000,
  market_value_minor: 750_000,
  unrealized_gain_minor: 250_000,
  unrealized_gain_pct: 50,
  realized_gain_minor: 30_000,
  dividend_income_minor: 12_000,
  total_return_minor: 292_000,
  holding_count: 4,
  unpriced_count: 0,
  priced_as_of: "2026-08-03",
  stale_count: 0,
  asset_allocation: [],
  sector_allocation: [],
  account_allocation: [],
};

function renderCard(overrides: Partial<PortfolioSummary> = {}) {
  return render(<PortfolioSummaryCard summary={{ ...SUMMARY, ...overrides }} />);
}

describe("PortfolioSummaryCard", () => {
  it("keeps the four kinds of return visually distinct", () => {
    // Blurring these is how people believe they have money they haven't made.
    renderCard();
    expect(screen.getByText("Cost basis")).toBeInTheDocument();
    expect(screen.getByText("Realised gains")).toBeInTheDocument();
    expect(screen.getByText("Dividends")).toBeInTheDocument();
    expect(screen.getByText("Total return")).toBeInTheDocument();
  });

  it("labels the paper gain as unrealised", () => {
    renderCard();
    expect(screen.getByText(/unrealised/i)).toBeInTheDocument();
    expect(screen.getByText(/\+50%/)).toBeInTheDocument();
  });

  it("keeps the sign on a loss", () => {
    renderCard({ realized_gain_minor: -30_000, total_return_minor: -18_000 });
    // formatAmount() strips the sign; a -$300 loss shown as "$300" reads as a
    // gain.
    expect(screen.getAllByText(/-\$300\.00/).length).toBeGreaterThan(0);
  });

  it("warns when the total is partial", () => {
    renderCard({ unpriced_count: 2, holding_count: 5 });
    // An incomplete total presented as complete is a lie of omission.
    expect(screen.getByText(/2 of 5 holdings have no price/i)).toBeInTheDocument();
  });

  it("shows no caveat when everything is priced", () => {
    renderCard({ unpriced_count: 0 });
    expect(screen.queryByText(/no price yet/i)).not.toBeInTheDocument();
  });

  it("says when a valuation is not today's", () => {
    // Quotes are typed in by hand, so "market value" is only as current as the
    // last time someone updated a price. Rendering a six-month-old quote as
    // what the portfolio is worth today is the one thing a valuation must not
    // do, and before this the date was discarded by the selector entirely.
    renderCard({ priced_as_of: "2026-03-12", stale_count: 3 });
    expect(screen.getByText(/prices last updated March 12, 2026/i)).toBeInTheDocument();
    expect(screen.getByText(/not today's market/i)).toBeInTheDocument();
    expect(screen.getByText(/entered by hand/i)).toBeInTheDocument();
  });

  it("stays quiet when the prices are today's", () => {
    renderCard({ priced_as_of: "2026-08-03", stale_count: 0 });
    expect(screen.getByText(/at today's prices/i)).toBeInTheDocument();
    expect(screen.queryByText(/not today's market/i)).not.toBeInTheDocument();
  });

  it("marks the estimated figures as projected and the booked ones as settled", () => {
    // The distinction the card's docstring had always described and nothing on
    // screen encoded: market value and total return are derived from a
    // hand-entered price, while cost basis, realised gains and dividends are
    // ledger facts.
    const { container } = renderCard();
    const certainty = (label: string) =>
      [...container.querySelectorAll(".lf-figure")]
        .find((f) => f.querySelector(".lf-figure-label")?.textContent === label)
        ?.getAttribute("data-certainty");

    expect(certainty("Market value")).toBe("projected");
    expect(certainty("Total return")).toBe("projected");
    expect(certainty("Cost basis")).toBe("settled");
    expect(certainty("Realised gains")).toBe("settled");
    expect(certainty("Dividends")).toBe("settled");
  });
});
