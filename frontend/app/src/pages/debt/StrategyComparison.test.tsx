import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { StrategyComparison as Comparison } from "../../api/types";
import { StrategyComparison } from "./StrategyComparison";

const COMPARISONS: Comparison[] = [
  {
    strategy: "avalanche",
    months_to_debt_free: 24,
    debt_free_on: "2028-01-15",
    total_interest_minor: 199_022,
    interest_saved_minor: 40_000,
    months_saved: 6,
    first_cleared_name: "Big expensive",
    first_cleared_months: 18,
  },
  {
    strategy: "snowball",
    months_to_debt_free: 25,
    debt_free_on: "2028-02-15",
    total_interest_minor: 214_036,
    interest_saved_minor: 25_000,
    months_saved: 5,
    first_cleared_name: "Small cheap",
    first_cleared_months: 2,
  },
  {
    strategy: "custom",
    months_to_debt_free: 25,
    debt_free_on: "2028-02-15",
    total_interest_minor: 214_036,
    interest_saved_minor: 25_000,
    months_saved: 5,
    first_cleared_name: "Small cheap",
    first_cleared_months: 2,
  },
];

function renderComparison(props = {}) {
  return render(
    <StrategyComparison
      comparisons={COMPARISONS}
      selected="avalanche"
      currency="USD"
      onSelect={vi.fn()}
      {...props}
    />,
  );
}

describe("StrategyComparison", () => {
  it("presents the strategies side by side rather than picking one", () => {
    // Which suits someone is a judgement about them, not arithmetic.
    renderComparison();
    expect(screen.getByText("Highest rate first")).toBeInTheDocument();
    expect(screen.getByText("Smallest balance first")).toBeInTheDocument();
    expect(screen.getByText("Your own order")).toBeInTheDocument();
  });

  it("shows the trade-off each method is making", () => {
    renderComparison();
    expect(screen.getByText(/costs the least in interest/i)).toBeInTheDocument();
    expect(screen.getByText(/clears individual debts sooner/i)).toBeInTheDocument();
  });

  it("names the first debt each strategy clears, and when", () => {
    // Snowball's entire argument, made visible.
    renderComparison();
    // Snowball and custom share a first-cleared debt in this fixture, so both
    // rows match — assert on the count rather than assuming uniqueness.
    expect(screen.getAllByText(/First clears Small cheap in 2 mo/i)).toHaveLength(2);
    expect(screen.getByText(/First clears Big expensive in 1y 6m/i)).toBeInTheDocument();
  });

  it("formats long timelines in years and months", () => {
    renderComparison({
      comparisons: [{ ...COMPARISONS[0], months_to_debt_free: 30 }],
    });
    expect(screen.getByText("2y 6m")).toBeInTheDocument();
  });

  it("shows a dash rather than a number when a plan cannot finish", () => {
    // Inventing a date for a debt that never clears would be the worst
    // possible answer here.
    renderComparison({
      comparisons: [{ ...COMPARISONS[0], months_to_debt_free: null }],
    });
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("marks the selected strategy as a radio option", () => {
    renderComparison({ selected: "snowball" });
    const options = screen.getAllByRole("radio");
    const snowball = options.find((o) => o.textContent?.includes("Smallest balance"));
    expect(snowball).toHaveAttribute("aria-checked", "true");
  });

  it("emits the strategy on selection", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    renderComparison({ onSelect });
    await user.click(screen.getByText("Smallest balance first"));
    expect(onSelect).toHaveBeenCalledWith("snowball");
  });

  it("renders nothing without comparisons", () => {
    const { container } = renderComparison({ comparisons: [] });
    expect(container).toBeEmptyDOMElement();
  });
});
