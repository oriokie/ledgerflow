import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CashflowCalendar, CashflowCalendarDay } from "../../api/types";

// Recharts renders nothing measurable in jsdom and animates from rAF frames
// that never arrive; this suite is about the *claims* the card makes.
vi.mock("recharts", () => {
  const Stub = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    ResponsiveContainer: Stub,
    AreaChart: Stub,
    Area: () => null,
    XAxis: () => null,
    YAxis: () => null,
    Tooltip: () => null,
    ReferenceLine: () => null,
  };
});

import { CashflowOutlook } from "./CashflowOutlook";

function day(d: string, closing: number, over: Partial<CashflowCalendarDay> = {}): CashflowCalendarDay {
  return {
    day: d,
    opening_minor: closing,
    closing_minor: closing,
    inflow_minor: 0,
    outflow_minor: 0,
    net_minor: 0,
    is_negative: closing < 0,
    expected_minor: null,
    expected_low_minor: null,
    expected_high_minor: null,
    events: [],
    ...over,
  };
}

function calendar(over: Partial<CashflowCalendar> = {}): CashflowCalendar {
  return {
    currency: "USD",
    start: "2026-08-01",
    end: "2026-08-03",
    opening_balance_minor: 100_000,
    closing_balance_minor: 100_000,
    lowest_balance_minor: 100_000,
    safe_to_spend_minor: 0,
    safe_to_spend_basis: "scheduled" as const,
    lowest_balance_on: "2026-08-01",
    first_negative_on: null,
    negative_day_count: 0,
    everyday: null,
    days: [day("2026-08-01", 100_000), day("2026-08-02", 100_000), day("2026-08-03", 100_000)],
    ...over,
  };
}

describe("CashflowOutlook", () => {
  it("admits the projection is a best case when spending cannot be estimated", () => {
    // A schedule-only line is not merely uncertain, it is systematically
    // optimistic: it draws a flat balance across a fortnight in which the user
    // will certainly spend money, and tells someone they are fine when they
    // are not. If the band can't be measured, that has to be said.
    render(<CashflowOutlook calendar={calendar({ everyday: null })} />);
    expect(screen.getByText(/bills and recurring items only/i)).toBeInTheDocument();
    expect(screen.getByText(/treat it as the best case/i)).toBeInTheDocument();
  });

  it("states what the band was measured from", () => {
    // A shaded region with no stated basis is decoration pretending to be
    // rigour.
    render(
      <CashflowOutlook
        calendar={calendar({
          everyday: {
            mean_minor: 1_500,
            stdev_minor: 2_400,
            median_minor: 0,
            observed_days: 90,
            active_days: 61,
          },
        })}
      />,
    );
    expect(screen.getByText(/90 days of your history/i)).toBeInTheDocument();
    expect(screen.getByText(/61 of them/i)).toBeInTheDocument();
    expect(screen.getByText(/the range that total usually lands in/i)).toBeInTheDocument();
    expect(screen.queryByText(/treat it as the best case/i)).not.toBeInTheDocument();
  });
});
