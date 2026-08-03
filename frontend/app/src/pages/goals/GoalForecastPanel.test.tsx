import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { GoalForecast } from "../../api/types";
import { GoalForecastPanel } from "./GoalForecastPanel";

// Recharts needs layout measurement that jsdom doesn't provide; the chart is
// decorative here (aria-hidden) and its data is asserted on the API side.
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

const BASE: GoalForecast = {
  goal_id: "g1",
  currency: "USD",
  saved_minor: 60_000,
  target_minor: 600_000,
  remaining_minor: 540_000,
  percent: 10,
  required_monthly_minor: 45_000,
  planned_monthly_minor: 30_000,
  observed_monthly_minor: 10_000,
  monthly_shortfall_minor: 35_000,
  projected_completion: "2029-01-15",
  target_date: "2027-06-01",
  on_track: false,
  success_probability: 0.2,
  consistency: 0.5,
  projection: [],
};

function renderPanel(overrides: Partial<GoalForecast> = {}) {
  return render(<GoalForecastPanel forecast={{ ...BASE, ...overrides }} />);
}

describe("GoalForecastPanel", () => {
  it("shows required, observed and planned as three separate figures", () => {
    renderPanel();
    // Collapsing these is what makes goal trackers useless once you fall behind.
    expect(screen.getByText("Needed monthly")).toBeInTheDocument();
    expect(screen.getByText("Your pace")).toBeInTheDocument();
    expect(screen.getByText("Planned")).toBeInTheDocument();
  });

  it("states the shortfall as the actionable next step", () => {
    renderPanel();
    expect(screen.getByText(/add/i)).toBeInTheDocument();
    expect(screen.getByText(/a month to reach this on time/i)).toBeInTheDocument();
  });

  it("omits the shortfall when the user is already keeping pace", () => {
    renderPanel({ monthly_shortfall_minor: 0 });
    expect(screen.queryByText(/a month to reach this on time/i)).not.toBeInTheDocument();
  });

  it("bands confidence rather than printing a false-precision percentage", () => {
    renderPanel({ success_probability: 0.2 });
    expect(screen.getByText(/unlikely at this pace/i)).toBeInTheDocument();
    // A heuristic shown to the point would imply precision the model lacks.
    expect(screen.queryByText(/20%/)).not.toBeInTheDocument();
  });

  it("moves through the confidence bands with the estimate", () => {
    const { unmount } = renderPanel({ success_probability: 0.85 });
    expect(screen.getByText(/on track to make it/i)).toBeInTheDocument();
    unmount();
    renderPanel({ success_probability: 0.5 });
    expect(screen.getByText(/could go either way/i)).toBeInTheDocument();
  });

  it("explains the absence of a probability instead of showing zero", () => {
    renderPanel({ success_probability: null });
    expect(screen.getByText(/we'll estimate your chances/i)).toBeInTheDocument();
    expect(screen.queryByText(/unlikely at this pace/i)).not.toBeInTheDocument();
  });

  it("says so when there is no history to derive a pace from", () => {
    renderPanel({ observed_monthly_minor: null });
    expect(screen.getByText(/not enough history/i)).toBeInTheDocument();
  });

  it("explains a missing completion estimate rather than inventing a date", () => {
    renderPanel({ projected_completion: null });
    expect(screen.getByText(/not on a trajectory yet/i)).toBeInTheDocument();
  });

  it("reports on-track status when the projection beats the target date", () => {
    renderPanel({ on_track: true, projected_completion: "2027-01-15" });
    expect(screen.getByText("On track")).toBeInTheDocument();
  });

  it("shows no target-date messaging for an undated goal", () => {
    renderPanel({ required_monthly_minor: null, target_date: null, on_track: null });
    expect(screen.getByText(/no target date/i)).toBeInTheDocument();
  });
});
