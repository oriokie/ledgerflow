import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const consolidated = {
  value: undefined as
    | { base_currency: string; total_minor: number; converted: boolean; currency_count: number }
    | undefined,
};
vi.mock("../../hooks/useFinance", () => ({
  useNetWorthBase: () => ({ data: consolidated.value }),
}));

import { NetWorthCard } from "./HeroCards";

const netWorth = { currency: "USD", assets_minor: 500_00, liabilities_minor: 100_00, net_minor: 400_00 };

describe("NetWorthCard consolidation", () => {
  it("shows a base-currency roll-up when several currencies are held", () => {
    consolidated.value = { base_currency: "USD", total_minor: 208_70, converted: true, currency_count: 2 };
    render(
      <MemoryRouter>
        <NetWorthCard netWorth={netWorth} history={undefined} currency="USD" />
      </MemoryRouter>,
    );
    expect(screen.getByText(/total across 2 currencies/i)).toBeInTheDocument();
  });

  it("flags an incomplete roll-up instead of implying precision", () => {
    consolidated.value = { base_currency: "USD", total_minor: 100_00, converted: false, currency_count: 3 };
    render(
      <MemoryRouter>
        <NetWorthCard netWorth={netWorth} history={undefined} currency="USD" />
      </MemoryRouter>,
    );
    expect(screen.getByText(/some rates unavailable/i)).toBeInTheDocument();
  });

  it("stays quiet for a single-currency workspace", () => {
    consolidated.value = { base_currency: "USD", total_minor: 400_00, converted: true, currency_count: 1 };
    render(
      <MemoryRouter>
        <NetWorthCard netWorth={netWorth} history={undefined} currency="USD" />
      </MemoryRouter>,
    );
    expect(screen.queryByText(/total across/i)).not.toBeInTheDocument();
  });
});
