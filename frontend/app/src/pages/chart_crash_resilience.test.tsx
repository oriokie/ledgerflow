/**
 * Crash probe: feed every chart component the edge-case data real API
 * responses can legitimately produce (empty arrays, zero values, single data
 * points) and confirm none of them throw during render. This is exactly the
 * failure mode a missing error boundary made catastrophic — before it
 * existed, one bad prop shape from any of these would have blanked the
 * entire page.
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CashFlowChart } from "./analytics/CashFlowChart";
import { AllocationChart } from "./investments/AllocationChart";
import { PerformanceChart } from "./investments/PerformanceChart";

describe("chart resilience against edge-case data", () => {
  it("CashFlowChart survives an empty trend", () => {
    expect(() => render(<CashFlowChart trend={[]} currency="USD" />)).not.toThrow();
  });

  it("CashFlowChart survives a single data point", () => {
    expect(() =>
      render(
        <CashFlowChart
          trend={[{ period_start: "2026-01-01", income_minor: 100000, expense_minor: 50000, net_minor: 50000 }]}
          currency="USD"
        />,
      ),
    ).not.toThrow();
  });

  it("CashFlowChart survives all-zero values", () => {
    expect(() =>
      render(
        <CashFlowChart
          trend={[{ period_start: "2026-01-01", income_minor: 0, expense_minor: 0, net_minor: 0 }]}
          currency="USD"
        />,
      ),
    ).not.toThrow();
  });

  it("AllocationChart survives an empty slice list", () => {
    expect(() => render(<AllocationChart title="By class" slices={[]} currency="USD" />)).not.toThrow();
  });

  it("AllocationChart survives a slice with zero percent", () => {
    expect(() =>
      render(
        <AllocationChart
          title="By class"
          slices={[{ label: "Cash", market_value_minor: 0, percent: 0 }]}
          currency="USD"
        />,
      ),
    ).not.toThrow();
  });

  it("PerformanceChart survives an empty history", () => {
    expect(() => render(<PerformanceChart points={[]} currency="USD" />)).not.toThrow();
  });

  it("PerformanceChart survives a single point with zero cost basis", () => {
    expect(() =>
      render(
        <PerformanceChart
          points={[{ as_of: "2026-01-01", market_value_minor: 0, cost_basis_minor: 0, unrealized_gain_minor: 0 }]}
          currency="USD"
        />,
      ),
    ).not.toThrow();
  });

  it("PerformanceChart survives negative unrealized gain (a real loss)", () => {
    expect(() =>
      render(
        <PerformanceChart
          points={[
            { as_of: "2026-01-01", market_value_minor: 80_000, cost_basis_minor: 100_000, unrealized_gain_minor: -20_000 },
          ]}
          currency="USD"
        />,
      ),
    ).not.toThrow();
  });
});
