import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DebtAnalytics as Analytics } from "../../api/types";

// Recharts needs layout measurement jsdom doesn't provide; the charts are
// decorative here and their data is asserted on the API side.
vi.mock("recharts", () => {
  const Stub = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    ResponsiveContainer: Stub,
    BarChart: Stub,
    AreaChart: Stub,
    Bar: () => null,
    Area: () => null,
    XAxis: () => null,
    YAxis: () => null,
    Tooltip: () => null,
    Legend: () => null,
  };
});

import { DebtAnalytics } from "./DebtAnalytics";

const ANALYTICS: Analytics = {
  currency: "USD",
  strategy: "avalanche",
  opening_balance_minor: 600_000,
  series: [
    {
      as_of: "2026-03-15",
      interest_minor: 9_000,
      fees_minor: 500,
      principal_minor: 20_500,
      cumulative_interest_minor: 9_000,
      cumulative_principal_minor: 20_500,
      remaining_balance_minor: 579_500,
    },
  ],
  composition: [{ kind: "credit_card", balance_minor: 600_000, percent: 100 }],
  monthly_velocity_minor: 20_500,
  total_interest_minor: 120_000,
  total_fees_minor: 6_000,
  months_to_debt_free: 24,
  debt_free_on: "2028-03-15",
};

function renderAnalytics(overrides: Partial<Analytics> = {}) {
  return render(
    <DebtAnalytics analytics={{ ...ANALYTICS, ...overrides }} exportPath="/export.csv" />,
  );
}

// The export endpoints are tenant-scoped, so downloads go through the
// authenticated client rather than a bare anchor. Mocked here to assert the
// control calls it with the right path.
const downloadFile = vi.fn().mockResolvedValue(undefined);
vi.mock("../../lib/download", () => ({ downloadFile: (...a: unknown[]) => downloadFile(...a) }));

describe("DebtAnalytics", () => {
  it("leads with how fast the balance is actually falling", () => {
    renderAnalytics();
    expect(screen.getByText("Coming off the balance")).toBeInTheDocument();
    expect(screen.getByText("per month")).toBeInTheDocument();
  });

  it("separates interest from fees over the plan", () => {
    renderAnalytics();
    expect(screen.getByText("Interest over the plan")).toBeInTheDocument();
    expect(screen.getByText("Fees over the plan")).toBeInTheDocument();
  });

  it("omits the fees figure when there are none", () => {
    renderAnalytics({ total_fees_minor: 0 });
    expect(screen.queryByText("Fees over the plan")).not.toBeInTheDocument();
  });

  it("says which part of a payment reduces the debt without relying on colour", () => {
    // This test used to assert the caption "Green reduces what you owe. Red and
    // amber don't." under a comment claiming the point was "stated rather than
    // left to the colours" — while asserting the sentence that *was* the
    // colours. Naming a band only by its hue is WCAG 1.4.1: a deuteranopic
    // reader gets nothing. The caption names the parts and their stacking
    // order instead, which is a colour-free encoding.
    renderAnalytics();
    expect(screen.getByText(/principal at the bottom, then interest, then fees/i)).toBeInTheDocument();
    expect(screen.getByText(/only the principal\s+reduces what you owe/i)).toBeInTheDocument();
    expect(screen.queryByText(/\b(green|red|amber)\b/i)).not.toBeInTheDocument();
  });

  it("downloads the schedule through the authenticated client", async () => {
    renderAnalytics();
    const button = screen.getByRole("button", { name: /export schedule/i });
    expect(screen.queryByRole("link", { name: /export schedule/i })).not.toBeInTheDocument();

    fireEvent.click(button);
    await waitFor(() =>
      expect(downloadFile).toHaveBeenCalledWith("/export.csv", "payoff-schedule.csv"),
    );
  });

  it("tells the user when an export fails instead of failing silently", async () => {
    downloadFile.mockRejectedValueOnce(new Error("network"));
    renderAnalytics();

    fireEvent.click(screen.getByRole("button", { name: /export schedule/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/could not export/i));
  });
});
