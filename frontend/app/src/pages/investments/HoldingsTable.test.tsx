import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { HoldingValuation } from "../../api/types";
import { HoldingsTable } from "./HoldingsTable";

const HOLDING: HoldingValuation = {
  holding_id: "h1",
  account_id: "a1",
  account_name: "Brokerage",
  security_id: "s1",
  symbol: "ACME",
  security_name: "Acme Inc",
  asset_class: "stock",
  sector: "Technology",
  currency: "USD",
  quantity: "10.00000000",
  cost_basis_minor: 50_000,
  price_minor: 7_500,
  market_value_minor: 75_000,
  unrealized_gain_minor: 25_000,
  unrealized_gain_pct: 50,
  priced_as_of: "2026-08-03",
  is_priced: true,
};

describe("HoldingsTable", () => {
  it("shows cost and value side by side so the gain can be checked", () => {
    render(<HoldingsTable holdings={[HOLDING]} />);
    // <Money> renders the whole and the cents as separate spans, so assert on
    // the row's text rather than a single node.
    const row = screen.getByText("ACME").closest("tr")!;
    expect(row.textContent).toContain("$500");
    expect(row.textContent).toContain("$750");
  });

  it("trims trailing zeros from whole quantities", () => {
    render(<HoldingsTable holdings={[HOLDING]} />);
    expect(screen.getByText("10")).toBeInTheDocument();
  });

  it("keeps fractional precision for crypto", () => {
    render(<HoldingsTable holdings={[{ ...HOLDING, quantity: "0.05230000", symbol: "BTC" }]} />);
    expect(screen.getByText("0.0523")).toBeInTheDocument();
  });

  it("says an unpriced holding is not priced rather than showing zero", () => {
    // A zero in a market-value column reads as a total loss.
    render(
      <HoldingsTable
        holdings={[
          {
            ...HOLDING,
            price_minor: null,
            market_value_minor: null,
            unrealized_gain_minor: null,
            unrealized_gain_pct: null,
            is_priced: false,
          },
        ]}
      />,
    );
    expect(screen.getByText("Not priced")).toBeInTheDocument();
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
  });

  it("marks a loss without relying on colour alone", () => {
    render(
      <HoldingsTable
        holdings={[{ ...HOLDING, unrealized_gain_minor: -10_000, unrealized_gain_pct: -20 }]}
      />,
    );
    const row = screen.getByText("ACME").closest("tr")!;
    expect(within(row).getByText(/-\$100\.00/)).toBeInTheDocument();
    expect(within(row).getByText(/-20%/)).toBeInTheDocument();
  });
  it("dates a holding whose price is not today's", () => {
    // The summary card says the portfolio total is stale. Without a per-row
    // signal the reader is told that and given no way to find the culprit.
    render(<HoldingsTable holdings={[{ ...HOLDING, priced_as_of: "2026-03-24" }]} />);
    expect(screen.getByText(/at Mar 24 price/i)).toBeInTheDocument();
  });

  it("says nothing extra when the price is today's", () => {
    const d = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    const today = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    render(<HoldingsTable holdings={[{ ...HOLDING, priced_as_of: today }]} />);
    expect(screen.queryByText(/price$/i)).not.toBeInTheDocument();
  });
});
