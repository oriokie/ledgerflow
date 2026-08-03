import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BreakdownRowWithShare } from "./analyticsMath";
import { CategoryBreakdown } from "./CategoryBreakdown";

const rows: BreakdownRowWithShare[] = [
  { category_id: "a", category_name: "Food", amount_minor: 6000, share: 0.6 },
  { category_id: "b", category_name: "Transport", amount_minor: 4000, share: 0.4 },
];

describe("CategoryBreakdown", () => {
  it("renders each category with its share", () => {
    render(<CategoryBreakdown rows={rows} selectedId={null} onSelect={() => {}} currency="USD" />);
    expect(screen.getByText("Food")).toBeInTheDocument();
    expect(screen.getByText("Transport")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
  });

  it("drills into a category on click", () => {
    const onSelect = vi.fn();
    render(<CategoryBreakdown rows={rows} selectedId={null} onSelect={onSelect} currency="USD" />);
    fireEvent.click(screen.getByRole("button", { name: /Food/ }));
    expect(onSelect).toHaveBeenCalledWith("a", "Food");
  });

  it("marks the selected row", () => {
    render(<CategoryBreakdown rows={rows} selectedId="b" onSelect={() => {}} currency="USD" />);
    expect(screen.getByRole("button", { name: /Transport/ })).toHaveAttribute("data-selected", "true");
  });

  it("shows an empty note with no rows", () => {
    render(<CategoryBreakdown rows={[]} selectedId={null} onSelect={() => {}} currency="USD" />);
    expect(screen.getByText(/no activity/i)).toBeInTheDocument();
  });
});
