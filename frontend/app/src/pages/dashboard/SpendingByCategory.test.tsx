import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CategoryBreakdownRow } from "../../api/types";
import { SpendingByCategory } from "./SpendingByCategory";

function makeRows(n: number): CategoryBreakdownRow[] {
  return Array.from({ length: n }, (_, i) => ({
    category_id: `c${i}`,
    category_name: `Category ${i}`,
    amount_minor: (n - i) * 1000,
  }));
}

describe("SpendingByCategory — progressive disclosure", () => {
  it("previews the top 6 and expands to show the rest", () => {
    render(<SpendingByCategory breakdown={makeRows(8)} currency="USD" />);

    // Top 6 visible, 7th and 8th hidden until expanded.
    expect(screen.getByText("Category 0")).toBeInTheDocument();
    expect(screen.getByText("Category 5")).toBeInTheDocument();
    expect(screen.queryByText("Category 6")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /show all 8/i }));

    expect(screen.getByText("Category 6")).toBeInTheDocument();
    expect(screen.getByText("Category 7")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /show less/i })).toBeInTheDocument();
  });

  it("does not show a toggle when everything already fits", () => {
    render(<SpendingByCategory breakdown={makeRows(4)} currency="USD" />);
    expect(screen.queryByRole("button", { name: /show all/i })).not.toBeInTheDocument();
  });

  it("shows an empty state when there is no spending", () => {
    render(<SpendingByCategory breakdown={[]} currency="USD" />);
    expect(screen.getByText(/no spending yet/i)).toBeInTheDocument();
  });
});
