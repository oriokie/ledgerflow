import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PayoffCalendarMonth } from "../../api/types";
import { PayoffCalendar } from "./PayoffCalendar";

const MONTH: PayoffCalendarMonth = {
  as_of: "2026-03-15",
  total_paid_minor: 30_000,
  total_interest_minor: 8_000,
  remaining_balance_minor: 470_000,
  payments: [
    {
      debt_id: "d1",
      name: "Visa",
      payment_minor: 20_000,
      interest_minor: 8_000,
      principal_minor: 12_000,
      balance_after_minor: 470_000,
      clears_here: false,
    },
  ],
};

describe("PayoffCalendar", () => {
  it("groups by month, because that's how the money leaves", () => {
    render(<PayoffCalendar months={[MONTH]} currency="USD" />);
    expect(screen.getByText("March 2026")).toBeInTheDocument();
  });

  it("splits each payment into interest and principal", () => {
    // Seeing that most of a payment went to interest explains a balance that
    // has barely moved.
    render(<PayoffCalendar months={[MONTH]} currency="USD" />);
    expect(screen.getByText(/\$80\.00 interest/)).toBeInTheDocument();
    expect(screen.getByText(/\$120\.00 off the balance/)).toBeInTheDocument();
  });

  it("celebrates the month a debt clears", () => {
    render(
      <PayoffCalendar
        months={[{ ...MONTH, payments: [{ ...MONTH.payments[0], clears_here: true }] }]}
        currency="USD"
      />,
    );
    expect(screen.getByText(/paid off/i)).toBeInTheDocument();
  });

  it("explains an empty schedule rather than showing a blank list", () => {
    render(<PayoffCalendar months={[]} currency="USD" />);
    expect(screen.getByText(/add an interest rate and minimum payment/i)).toBeInTheDocument();
  });
});
