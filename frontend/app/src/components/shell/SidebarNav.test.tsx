import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

let mockUser: { show_receipt_scanner?: boolean } | null = null;
vi.mock("../../lib/AuthContext", () => ({ useAuth: () => ({ user: mockUser }) }));
vi.mock("../../hooks/useRoutePrefetch", () => ({ useRoutePrefetch: () => () => {} }));
vi.mock("../../hooks/useRailMetrics", () => ({ useRailMetrics: () => ({}), metricFor: () => undefined }));
vi.mock("../../lib/featureFlags", () => ({ useFlag: () => [false, vi.fn()] }));
vi.mock("../../lib/pinnedViews", () => ({ usePinnedViews: () => ({ pinned: [] }) }));

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
