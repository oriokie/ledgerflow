import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

let mockUser: { show_receipt_scanner?: boolean } | null = null;
vi.mock("../../lib/AuthContext", () => ({ useAuth: () => ({ user: mockUser }) }));
vi.mock("../../hooks/useRoutePrefetch", () => ({ useRoutePrefetch: () => () => {} }));
vi.mock("../../hooks/useRailMetrics", () => ({ useRailMetrics: () => ({}), metricFor: () => undefined }));
vi.mock("../../lib/featureFlags", () => ({ useFlag: () => [false, vi.fn()] }));
vi.mock("../../lib/pinnedViews", () => ({ usePinnedViews: () => ({ pinned: [] }) }));
vi.mock("../../hooks/useEntitlements", async (importOriginal) => {
  const original = await importOriginal<typeof import("../../hooks/useEntitlements")>();
  return {
    ...original,
    // These tests exercise the receipt-scanner preference; the plan filter is
    // covered by its own tests, so everything is entitled here.
    useFeatures: () => ({
      has: () => true,
      lapsed: false,
      trialing: false,
      trialDaysLeft: null,
      isLoading: false,
    }),
  };
});

import { SidebarNav } from "./SidebarNav";

beforeEach(() => {
  mockUser = null;
});

const renderNav = () =>
  render(
    <MemoryRouter>
      <SidebarNav />
    </MemoryRouter>,
  );

describe("SidebarNav — receipt scanning is opt-in", () => {
  it("hides Scan Receipt by default", () => {
    mockUser = {};
    renderNav();
    expect(screen.queryByText("Scan Receipt")).not.toBeInTheDocument();
  });

  it("shows it once the user has turned it on", () => {
    mockUser = { show_receipt_scanner: true };
    renderNav();
    expect(screen.getByText("Scan Receipt")).toBeInTheDocument();
  });

  it("hides it while the session is still loading rather than flashing it", () => {
    mockUser = null;
    renderNav();
    expect(screen.queryByText("Scan Receipt")).not.toBeInTheDocument();
  });

  it("leaves every other entry alone", () => {
    // Filtering a list is easy to get wrong in a way that drops neighbours.
    mockUser = {};
    renderNav();
    expect(screen.getByText("Quick Add")).toBeInTheDocument();
    expect(screen.getByText("Coach")).toBeInTheDocument();
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });
});

describe("SidebarNav — plan gating", () => {
  it("a Basic sidebar simply does not offer the Plus features", async () => {
    // A menu of doors that open onto paywalls reads as nagging, not
    // navigation. The backend answers 402 either way; this is presentation.
    const entitlements = await import("../../hooks/useEntitlements");
    const basic = new Set(["budgets", "bills", "recurring", "goals"]);
    vi.spyOn(entitlements, "useFeatures").mockReturnValue({
      has: (feature: string) => basic.has(feature),
      lapsed: false,
      trialing: true,
      trialDaysLeft: 5,
      isLoading: false,
    });
    mockUser = {};
    renderNav();

    expect(screen.queryByText("Investments")).not.toBeInTheDocument();
    expect(screen.queryByText("Debt")).not.toBeInTheDocument();
    expect(screen.queryByText("Coach")).not.toBeInTheDocument();
    expect(screen.getByText("Budgets")).toBeInTheDocument();
    expect(screen.getByText("Transactions")).toBeInTheDocument();
  });
});
