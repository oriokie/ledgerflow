import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { CashflowCalendar as Calendar, CashflowCalendarDay } from "../../api/types";
import { CashflowCalendar } from "./CashflowCalendar";

function makeDay(iso: string, closing: number, overrides: Partial<CashflowCalendarDay> = {}) {
  return {
    day: iso,
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
    ...overrides,
  } satisfies CashflowCalendarDay;
}

const SALARY = {
  occurs_on: "2026-07-28",
  amount_minor: 300_000,
  description: "Monthly salary",
  source: "salary" as const,
  currency: "USD",
  account_id: "a1",
  account_name: "Checking",
  category_name: "Income",
  is_overdue: false,
  bill_id: null,
  recurring_id: "r1",
};

const RENT = {
  ...SALARY,
  occurs_on: "2026-07-27",
  amount_minor: -120_000,
  description: "Rent",
  source: "bill" as const,
  recurring_id: null,
  bill_id: "b1",
};

function makeCalendar(overrides: Partial<Calendar> = {}): Calendar {
  return {
    currency: "USD",
    start: "2026-07-27",
    end: "2026-07-29",
    opening_balance_minor: 100_000,
    closing_balance_minor: 280_000,
    lowest_balance_minor: -20_000,
    safe_to_spend_minor: 0,
    safe_to_spend_basis: "scheduled" as const,
    lowest_balance_on: "2026-07-27",
    first_negative_on: "2026-07-27",
    negative_day_count: 1,
    everyday: null,
    days: [
      makeDay("2026-07-27", -20_000, { events: [RENT], outflow_minor: 120_000, net_minor: -120_000 }),
      makeDay("2026-07-28", 280_000, { events: [SALARY], inflow_minor: 300_000, net_minor: 300_000 }),
      makeDay("2026-07-29", 280_000),
    ],
    ...overrides,
  };
}

describe("CashflowCalendar", () => {
  it("does not restate the summary figures", () => {
    // Leading with the trough is still the rule — it just belongs to the page,
    // which owns the summary card. The calendar used to print the low point
    // and the closing balance a second time, 200px below the first, in
    // different typography. Two numbers stated twice is two chances to
    // disagree about which one matters. Covered at the page level by
    // "leads with the trough, not just the closing balance".
    render(<CashflowCalendar calendar={makeCalendar()} />);
    expect(screen.queryByText(/projected low point/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/balance on/i)).not.toBeInTheDocument();
  });

  it("warns about a predicted overdraft with its date", () => {
    render(<CashflowCalendar calendar={makeCalendar()} />);
    const alert = screen.getByRole("status");
    expect(within(alert).getByText(/projected to go below zero/i)).toBeInTheDocument();
  });

  it("shows no overdraft warning when the balance never dips", () => {
    render(
      <CashflowCalendar
        calendar={makeCalendar({ first_negative_on: null, negative_day_count: 0, lowest_balance_minor: 50_000 })}
      />,
    );
    expect(screen.queryByText(/projected to go below zero/i)).not.toBeInTheDocument();
  });

  it("describes each day in full to assistive tech, not by colour alone", () => {
    render(<CashflowCalendar calendar={makeCalendar()} />);
    const cell = screen.getByRole("button", { name: /Predicted overdraft/i });
    expect(cell).toBeInTheDocument();
    // The sign must survive into the label: formatAmount() returns a magnitude,
    // which would announce a -$200 overdraft as a comfortable "$200.00".
    expect(cell).toHaveAccessibleName(expect.stringContaining("-$200.00"));
  });

  it("opens the day detail when a cell is clicked", async () => {
    const user = userEvent.setup();
    render(<CashflowCalendar calendar={makeCalendar()} />);

    await user.click(screen.getByRole("button", { name: /Predicted overdraft/i }));
    const dialog = await screen.findByRole("dialog", { hidden: true });
    expect(within(dialog).getByText("Rent")).toBeInTheDocument();
    expect(within(dialog).getByText("Opening")).toBeInTheDocument();
  });

  it("switches to the timeline view and lists only days with movement", async () => {
    const user = userEvent.setup();
    render(<CashflowCalendar calendar={makeCalendar()} />);

    await user.click(screen.getByRole("radio", { name: "Timeline" }));
    expect(screen.getByText("Rent")).toBeInTheDocument();
    expect(screen.getByText("Monthly salary")).toBeInTheDocument();
    // The quiet third day is omitted — a timeline of nothing is noise.
    expect(screen.queryByText("29 Jul")).not.toBeInTheDocument();
  });

  it("explains an empty timeline instead of showing a blank list", async () => {
    const user = userEvent.setup();
    render(
      <CashflowCalendar
        calendar={makeCalendar({
          days: [makeDay("2026-07-27", 100_000)],
          first_negative_on: null,
          negative_day_count: 0,
    everyday: null,
        })}
      />,
    );
    await user.click(screen.getByRole("radio", { name: "Timeline" }));
    expect(screen.getByText(/nothing scheduled in this window/i)).toBeInTheDocument();
  });

  it("pages through weeks in week view", async () => {
    const user = userEvent.setup();
    render(<CashflowCalendar calendar={makeCalendar()} />);

    await user.click(screen.getByRole("radio", { name: "Week" }));
    expect(screen.getByText(/week 1 of/i)).toBeInTheDocument();
    // Nothing before the start of the projection.
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
  });
});
