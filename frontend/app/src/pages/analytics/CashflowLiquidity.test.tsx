import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CashflowStatementData, CashRunway } from "../../api/types";
import { CashRunwayCard } from "../insights/CashRunwayCard";
import { CashflowStatement } from "./CashflowStatement";

const statement: CashflowStatementData = {
  currency: "USD",
  liquid_balance_minor: 600_000,
  rows: [
    { period_start: "2026-05-01", inflow_minor: 500_000, outflow_minor: 300_000, net_minor: 200_000, ending_balance_minor: 400_000 },
    { period_start: "2026-06-01", inflow_minor: 500_000, outflow_minor: 650_000, net_minor: -150_000, ending_balance_minor: 250_000 },
    { period_start: "2026-07-01", inflow_minor: 700_000, outflow_minor: 350_000, net_minor: 350_000, ending_balance_minor: 600_000 },
  ],
};

vi.mock("../../hooks/useFinance", () => ({
  useCashflowStatement: () => ({ data: statement, isLoading: false }),
}));

describe("CashflowStatement", () => {
  it("shows liquidity today, average net, and monthly rows with ending balances", () => {
    render(<CashflowStatement />);
    expect(screen.getByText(/liquid today/i)).toBeInTheDocument();
    expect(screen.getAllByText("$6,000.00").length).toBeGreaterThan(0); // liquid balance (also an ending row)
    // Avg monthly net over the 3 active months: (2000 - 1500 + 3500)/3 ≈ 1333.33.
    // Money conveys the sign through its own "in"/"out" class and colour, not a
    // literal "+" prefix — and splits cents into their own span (see Money's
    // ".lf-amount-cents" convention, ui/Figure.test.tsx), so match on the
    // whole-figure element rather than a single getByText string.
    const avgNetFigure = document.querySelector(".lf-amount--in");
    expect(avgNetFigure).toBeInTheDocument();
    expect(avgNetFigure?.textContent).toBe("$1,333.33");
    // Column headers + a negative-net month rendered.
    expect(screen.getByRole("columnheader", { name: /ending balance/i })).toBeInTheDocument();
    // Money's minus sign is the typographic U+2212, not an ASCII hyphen.
    const negativeNetFigure = document.querySelector(".lf-amount--out");
    expect(negativeNetFigure?.textContent).toBe("−$1,500.00");
    expect(screen.getAllByRole("row")).toHaveLength(4); // header + 3 months
  });
});

describe("CashRunwayCard", () => {
  it("states the projected run-out date plainly when critical", () => {
    const runway: CashRunway = {
      status: "critical",
      currency: "USD",
      liquid_balance_minor: 450_000,
      avg_monthly_net_minor: -150_000,
      months_analyzed: 3,
      upcoming_bills_minor: 120_000,
      upcoming_bills_count: 2,
      months_of_runway: 3,
      projected_runout_date: "2026-10-19",
    };
    render(<CashRunwayCard runway={runway} />);
    expect(screen.getByText(/could run out of cash around/i)).toBeInTheDocument();
    expect(screen.getByText(/2 bills .*due within 30 days/i)).toBeInTheDocument();
  });

  it("reassures when the trend is positive", () => {
    render(
      <CashRunwayCard
        runway={{ status: "healthy", currency: "USD", liquid_balance_minor: 900_000, avg_monthly_net_minor: 200_000, months_analyzed: 3, months_of_runway: null, projected_runout_date: null }}
      />,
    );
    expect(screen.getByText(/adding cash every month/i)).toBeInTheDocument();
  });

  it("is honest when there's not enough history", () => {
    render(<CashRunwayCard runway={{ status: "insufficient_data", reason: "not_enough_history" }} />);
    expect(screen.getByText(/not enough history/i)).toBeInTheDocument();
  });
});
