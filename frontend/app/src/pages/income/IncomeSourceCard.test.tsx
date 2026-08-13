import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { IncomeSource } from "../../api/income";
import { IncomeSourceCard } from "./IncomeSourceCard";

function source(overrides: Partial<IncomeSource> = {}): IncomeSource {
  return {
    id: "s1",
    name: "Monthly salary",
    kind: "employment",
    payer: "Acme",
    currency: "USD",
    frequency: "monthly",
    reliability: "fixed",
    is_active: true,
    starts_on: "2025-01-01",
    ends_on: null,
    is_current: true,
    stated_net_minor: 300_000,
    stated_gross_minor: 400_000,
    observed_mean_minor: null,
    observed_stdev_minor: null,
    receipt_count: 0,
    last_received_on: null,
    expected_net_minor: 300_000,
    expected_is_observed: false,
    monthly_net_minor: 300_000,
    deductions_minor: 100_000,
    variance_pct: null,
    is_speculative: false,
    ...overrides,
  };
}

const noop = vi.fn();

describe("IncomeSourceCard", () => {
  it("marks a figure with no history behind it as provisional, with its reason", () => {
    render(
      <IncomeSourceCard
        source={source({
          name: "Freelance",
          kind: "self_employment",
          reliability: "irregular",
          is_speculative: true,
          receipt_count: 0,
        })}
        onDelete={noop}
      />,
    );
    expect(screen.getByText("Provisional")).toBeInTheDocument();
    // The confidence statement is a required prop on a speculative Figure —
    // this asserts it actually reaches the screen.
    expect(screen.getByText(/haven't recorded any payments yet/i)).toBeInTheDocument();
  });

  it("says when the expected amount was measured rather than typed", () => {
    render(
      <IncomeSourceCard
        source={source({
          name: "Retainer",
          kind: "business",
          reliability: "variable",
          stated_net_minor: 100_000,
          expected_net_minor: 220_000,
          expected_is_observed: true,
          observed_mean_minor: 220_000,
          receipt_count: 3,
          variance_pct: 9.1,
        })}
        onDelete={noop}
      />,
    );
    
    expect(screen.getByText(/Average of 3 payments · ±9.1%/)).toBeInTheDocument();
    // The user's own number is not hidden — it is shown as what it is.
    expect(screen.getByText(/You entered/)).toBeInTheDocument();
  });

  it("shows a dash rather than a number when there is no monthly equivalent", () => {
    render(
      <IncomeSourceCard
        source={source({ frequency: "ad_hoc", monthly_net_minor: null })}
        onDelete={noop}
      />,
    );
    expect(screen.getByText("No set schedule")).toBeInTheDocument();
  });

  it("does not repeat the stated amount when it matches the expected one", () => {
    render(<IncomeSourceCard source={source()} onDelete={noop} />);
    expect(screen.queryByText(/You entered/)).not.toBeInTheDocument();
    expect(screen.queryByText("Provisional")).not.toBeInTheDocument();
  });
});
