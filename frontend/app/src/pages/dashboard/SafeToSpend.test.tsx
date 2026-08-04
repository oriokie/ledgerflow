import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CashflowCalendar } from "../../api/types";

let mockCalendar: Partial<CashflowCalendar> | undefined;
vi.mock("../../hooks/useFinance", () => ({
  useCashflowCalendar: () => ({ data: mockCalendar }),
}));

import { SafeToSpend } from "./SafeToSpend";

const CALENDAR: Partial<CashflowCalendar> = {
  currency: "USD",
  end: "2026-09-08",
  safe_to_spend_minor: 23_400,
  safe_to_spend_basis: "everyday",
  lowest_balance_minor: 23_400,
  lowest_balance_on: "2026-08-28",
};

beforeEach(() => {
  mockCalendar = CALENDAR;
});

const renderCard = () =>
  render(
    <MemoryRouter>
      <SafeToSpend />
    </MemoryRouter>,
  );

describe("SafeToSpend", () => {
  it("shows the figure with the everyday-spending caveat when history exists", () => {
    renderCard();
    expect(screen.getByText("$234.00")).toBeInTheDocument();
    expect(screen.getByText(/beyond your usual spending/i)).toBeInTheDocument();
  });

  it("caveats honestly when only scheduled bills could be projected", () => {
    // Claiming "beyond your usual spending" with no measured habits would
    // promise more than the projection knows.
    mockCalendar = { ...CALENDAR, safe_to_spend_basis: "scheduled" };
    renderCard();
    expect(screen.queryByText(/beyond your usual spending/i)).not.toBeInTheDocument();
    expect(screen.getByText(/every scheduled bill/i)).toBeInTheDocument();
  });

  it("zero explains the projected dip instead of just glowing red", () => {
    mockCalendar = {
      ...CALENDAR,
      safe_to_spend_minor: 0,
      lowest_balance_minor: -14_500,
    };
    renderCard();
    expect(screen.getByText(/nothing extra is safe right now/i)).toBeInTheDocument();
    expect(screen.getByText(/-\$145\.00/)).toBeInTheDocument();
  });

  it("renders nothing without a calendar rather than a zero", () => {
    // A safe-to-spend of zero derived from an absence of accounts would read
    // as an emergency rather than an unknown.
    mockCalendar = undefined;
    const { container } = renderCard();
    expect(container).toBeEmptyDOMElement();
  });
});
