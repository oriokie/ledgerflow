import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CommittedIncome, IncomeSummary } from "../../api/income";
import { CommittedIncomeCard } from "./CommittedIncomeCard";
import { committedBand } from "./incomeCopy";

function summary(committed: Partial<CommittedIncome> | null): IncomeSummary {
  return {
    currency: "USD",
    monthly_net_minor: 400_000,
    monthly_gross_minor: 500_000,
    monthly_fixed_minor: 400_000,
    monthly_variable_minor: 0,
    monthly_deductions_minor: 100_000,
    take_home_rate: 80,
    concentration_pct: 100,
    source_count: 1,
    ad_hoc_count: 0,
    speculative_count: 0,
    committed:
      committed === null
        ? null
        : {
            committed_minor: 150_000,
            free_minor: 250_000,
            committed_pct: 37.5,
            committed_against_fixed_pct: 37.5,
            bills_minor: 120_000,
            debt_minimums_minor: 0,
            recurring_expenses_minor: 30_000,
            ...committed,
          },
  };
}

describe("CommittedIncomeCard", () => {
  it("shows the ratio and what it is made of", () => {
    render(<CommittedIncomeCard summary={summary({})} />);

    expect(screen.getByText("37.5%")).toBeInTheDocument();
    expect(screen.getByText("Bills")).toBeInTheDocument();
    expect(screen.getByText("Debt minimums")).toBeInTheDocument();
    expect(screen.getByText("Recurring")).toBeInTheDocument();
    // A ratio nobody can take apart is a ratio nobody should act on.
    expect(screen.getByText(/one-off bills are real obligations/i)).toBeInTheDocument();
  });

  it("renders nothing when the ratio could not be computed", () => {
    // No income recorded means no denominator. Rendering "0%" here would read
    // as a clean bill of health derived from an absence.
    const { container } = render(<CommittedIncomeCard summary={summary(null)} />);
    expect(container).toBeEmptyDOMElement();

    const { container: nullPct } = render(
      <CommittedIncomeCard summary={summary({ committed_pct: null })} />,
    );
    expect(nullPct).toBeEmptyDOMElement();
  });

  it("surfaces the fixed-income ratio only when it says something different", () => {
    // Salaried: the two ratios are identical, so the second is noise.
    render(<CommittedIncomeCard summary={summary({ committed_against_fixed_pct: 37.5 })} />);
    expect(screen.queryByText(/do not vary with your earnings/i)).not.toBeInTheDocument();
  });

  it("warns when commitments outrun the income that is actually promised", () => {
    render(
      <CommittedIncomeCard
        summary={summary({ committed_pct: 25, committed_against_fixed_pct: 100 })}
      />,
    );
    // The rent is due whether or not the freelance work arrives — this is the
    // finding, and showing only the flattering ratio would bury it.
    expect(screen.getByText(/100% is committed/)).toBeInTheDocument();
  });
});

describe("committedBand", () => {
  it("moves through its three bands at the stated thresholds", () => {
    expect(committedBand(49.9).tone).toBe("positive");
    expect(committedBand(50).tone).toBe("warning");
    expect(committedBand(69.9).tone).toBe("warning");
    expect(committedBand(70).tone).toBe("critical");
  });
});
