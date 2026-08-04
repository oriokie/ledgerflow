import { fireEvent, render as rtlRender, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CashflowCalendar, CashflowCalendarDay } from "../api/types";

const useCashflowCalendar = vi.fn();
vi.mock("../hooks/useFinance", () => ({
  useCashflowCalendar: (args: unknown) => useCashflowCalendar(args),
}));

// The grid and the chart both pull in heavy children; this suite is about the
// page's own decisions — which horizon it asks for, and which view it opens.
vi.mock("./cashflow", () => ({
  CashflowCalendar: () => <div data-testid="grid" />,
  CashflowOutlook: () => <div data-testid="outlook" />,
}));

import { CashflowPage } from "./CashflowPage";

// The page links to /bills and /recurring from its empty state, so it needs a
// router in scope — rendering it bare only worked while it had no links.
const render = (ui: React.ReactElement) => rtlRender(<MemoryRouter>{ui}</MemoryRouter>);

/** A day that moves the balance — i.e. one worth drawing a calendar for. */
function activeDay(day: string, net: number): CashflowCalendarDay {
  return {
    day,
    opening_minor: 250_00,
    closing_minor: 250_00 + net,
    inflow_minor: net > 0 ? net : 0,
    outflow_minor: net < 0 ? -net : 0,
    net_minor: net,
    is_negative: 250_00 + net < 0,
    expected_minor: null,
    expected_low_minor: null,
    expected_high_minor: null,
    events: [],
  };
}

/** A day where nothing happens — the state a calendar should not be drawn for. */
function flatDay(day: string): CashflowCalendarDay {
  return { ...activeDay(day, 0), closing_minor: 250_00 };
}

function calendar(over: Partial<CashflowCalendar> = {}): CashflowCalendar {
  return {
    currency: "USD",
    start: "2026-07-01",
    end: "2026-08-30",
    opening_balance_minor: 250_00,
    closing_balance_minor: 400_00,
    lowest_balance_minor: 120_00,
    safe_to_spend_minor: 0,
    safe_to_spend_basis: "scheduled" as const,
    lowest_balance_on: "2026-07-18",
    first_negative_on: null,
    negative_day_count: 0,
    everyday: null,
    // Days that actually move. The fixture used to be `days: []`, which meant
    // every test here ran against a projection with nothing in it — the exact
    // state the page now refuses to draw a grid for.
    days: [activeDay("2026-07-01", -40_00), activeDay("2026-07-02", 190_00)],
    ...over,
  };
}

beforeEach(() => {
  useCashflowCalendar.mockReset();
  useCashflowCalendar.mockReturnValue({ data: calendar(), isLoading: false });
});

describe("CashflowPage", () => {
  it("offers six- and twelve-month horizons", () => {
    render(<CashflowPage />);
    expect(screen.getByLabelText("6 months")).toBeInTheDocument();
    expect(screen.getByLabelText("12 months")).toBeInTheDocument();
  });

  it("requests the full year from the API when twelve months is chosen", () => {
    render(<CashflowPage />);
    fireEvent.click(screen.getByLabelText("12 months"));
    // The backend has always allowed 365; the cap was only ever in the UI.
    expect(useCashflowCalendar).toHaveBeenLastCalledWith({ days: 365 });
  });

  it("opens on the grid for short windows", () => {
    render(<CashflowPage />);
    expect(screen.getByTestId("grid")).toBeInTheDocument();
  });

  it("opens on the outlook once the grid stops being readable", () => {
    render(<CashflowPage />);
    fireEvent.click(screen.getByLabelText("6 months"));
    expect(screen.getByTestId("outlook")).toBeInTheDocument();
    expect(screen.queryByTestId("grid")).not.toBeInTheDocument();
  });

  it("restores the grid when the user comes back to a short window", () => {
    render(<CashflowPage />);
    fireEvent.click(screen.getByLabelText("12 months"));
    fireEvent.click(screen.getByLabelText("5 weeks"));
    // Being stranded in an aggregate view of five weeks would be worse than
    // the wall of cells the aggregate exists to replace.
    expect(screen.getByTestId("grid")).toBeInTheDocument();
  });

  it("leads with the trough, not just the closing balance", () => {
    useCashflowCalendar.mockReturnValue({
      data: calendar({ lowest_balance_minor: 12_00, lowest_balance_on: "2026-07-18" }),
      isLoading: false,
    });
    render(<CashflowPage />);
    expect(screen.getByText("Lowest point")).toBeInTheDocument();
    expect(screen.getByText(/stays above zero/i)).toBeInTheDocument();
  });

  it("says outright when the projection goes underwater", () => {
    useCashflowCalendar.mockReturnValue({
      data: calendar({
        lowest_balance_minor: -80_00,
        negative_day_count: 4,
        first_negative_on: "2026-08-02",
      }),
      isLoading: false,
    });
    render(<CashflowPage />);
    expect(screen.getByText(/dips below zero/i)).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("refuses to draw a grid when every day is identical", () => {
    // Sixty cells all reading the same figure is the absence of a forecast,
    // not a forecast. The user's real situation — nothing is scheduled — was
    // the one thing the screen never said.
    useCashflowCalendar.mockReturnValue({
      data: calendar({ days: [flatDay("2026-07-01"), flatDay("2026-07-02")] }),
      isLoading: false,
    });
    render(<CashflowPage />);
    expect(screen.getByText(/nothing scheduled/i)).toBeInTheDocument();
    expect(screen.queryByTestId("grid")).not.toBeInTheDocument();
    // The summary still stands — those figures are real, just not a projection.
    expect(screen.getByText("Lowest point")).toBeInTheDocument();
    // And the hollow "stays above zero" verdict goes with the grid: it is true
    // of a flat line by construction, so it carries no information.
    expect(screen.queryByText(/stays above zero/i)).not.toBeInTheDocument();
  });

  it("keeps the grid when a flat total hides real movement", () => {
    // Inflow exactly cancelling outflow is a genuinely informative flatness,
    // and it must not be mistaken for having nothing scheduled.
    useCashflowCalendar.mockReturnValue({
      data: calendar({ days: [activeDay("2026-07-01", -50_00), activeDay("2026-07-02", 50_00)] }),
      isLoading: false,
    });
    render(<CashflowPage />);
    expect(screen.getByTestId("grid")).toBeInTheDocument();
  });

  it("shows the empty state rather than a zeroed projection when there's nothing to project", () => {
    // The API answers 204 here, which the client now surfaces as null — an
    // absence, not a balance of zero.
    useCashflowCalendar.mockReturnValue({ data: null, isLoading: false });
    render(<CashflowPage />);
    expect(screen.getByText(/nothing to project yet/i)).toBeInTheDocument();
    expect(screen.queryByText("Lowest point")).not.toBeInTheDocument();
  });
});
