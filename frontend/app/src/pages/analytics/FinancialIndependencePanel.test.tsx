import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FIProjection } from "../../api/types";

const projection = vi.fn();
vi.mock("../../api/reports", async (importOriginal) => {
  const original = await importOriginal<typeof import("../../api/reports")>();
  return { ...original, fiApi: { projection: () => projection() } };
});
vi.mock("../../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { tenant: { id: "t1" } } }),
}));

import { FinancialIndependencePanel } from "./FinancialIndependencePanel";

const BASE: FIProjection = {
  currency: "USD",
  as_of: "2026-08-04",
  months_measured: 6,
  monthly_spending_minor: 300_000,
  monthly_savings_minor: 150_000,
  net_worth_minor: 10_000_000,
  fi_number_minor: 90_000_000,
  swr: 0.04,
  progress_pct: 11.1,
  band: [
    { real_return: 0.04, years: 21.3, around_year: 2047 },
    { real_return: 0.05, years: 19.0, around_year: 2045 },
    { real_return: 0.06, years: 17.1, around_year: 2043 },
  ],
  never_at_current_pace: false,
  required_monthly_for_horizon_minor: null,
  horizon_years: 15,
  caveats: ["Returns are real (after inflation); today's money throughout."],
};

const renderPanel = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FinancialIndependencePanel />
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  vi.clearAllMocks();
  projection.mockResolvedValue(BASE);
});

describe("FinancialIndependencePanel", () => {
  it("headlines the middle of the band, in years not an age", async () => {
    renderPanel();
    expect(await screen.findByText(/optional in about 19 years — around 2045/i)).toBeInTheDocument();
  });

  it("always shows the sensitivity band beside the headline", async () => {
    // One confident year would be a lie of precision; the band is the honesty.
    renderPanel();
    expect(await screen.findByText("at 4% real")).toBeInTheDocument();
    expect(screen.getByText("at 6% real")).toBeInTheDocument();
    expect(screen.getByText(/21\.3 yrs/)).toBeInTheDocument();
  });

  it("prices the path in the never case instead of shrugging", async () => {
    projection.mockResolvedValue({
      ...BASE,
      never_at_current_pace: true,
      required_monthly_for_horizon_minor: 250_000,
      band: BASE.band.map((point) => ({ ...point, years: null, around_year: null })),
    });
    renderPanel();
    expect(await screen.findByText(/the path is priced/i)).toBeInTheDocument();
    expect(screen.getByText("$2,500.00/mo")).toBeInTheDocument();
  });

  it("thin history renders the explanation, not an error state", async () => {
    const { ApiError } = await import("../../api/client");
    projection.mockRejectedValue(
      new ApiError(404, { detail: "Fewer than two complete months of spending on record." }),
    );
    renderPanel();
    expect(await screen.findByText(/fewer than two complete months/i)).toBeInTheDocument();
  });
});
