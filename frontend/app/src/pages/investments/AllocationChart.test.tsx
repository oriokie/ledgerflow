import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AllocationSlice } from "../../api/types";
import { AllocationChart } from "./AllocationChart";

const slice = (label: string, percent: number, value: number): AllocationSlice => ({
  label,
  market_value_minor: value,
  percent,
});

const SLICES = [
  slice("Stocks", 55, 550_000),
  slice("Bonds", 30, 300_000),
  slice("Crypto", 15, 150_000),
];

function bar(container: HTMLElement) {
  return [...container.querySelectorAll(".lf-alloc-seg")].map((s) => ({
    rank: s.getAttribute("data-rank"),
    width: (s as HTMLElement).style.width,
  }));
}

describe("AllocationChart", () => {
  it("encodes each slice as length, in the order given", () => {
    // Length, not angle. Reading a proportion off a donut is a poor
    // perceptual task; a segment's width on a shared baseline is not.
    const { container } = render(<AllocationChart title="By asset" slices={SLICES} currency="USD" />);
    expect(bar(container)).toEqual([
      { rank: "1", width: "55%" },
      { rank: "2", width: "30%" },
      { rank: "3", width: "15%" },
    ]);
  });

  it("labels every slice directly, with an exact percentage and amount", () => {
    // The bar is aria-hidden; this list is the accessible representation, and
    // the ramp is redundant to it rather than the other way round.
    render(<AllocationChart title="By asset" slices={SLICES} currency="USD" />);
    for (const [label, pct] of [["Stocks", "55%"], ["Bonds", "30%"], ["Crypto", "15%"]]) {
      expect(screen.getByText(label)).toBeInTheDocument();
      expect(screen.getByText(pct)).toBeInTheDocument();
    }
    expect(screen.getByText("$5,500.00")).toBeInTheDocument();
  });

  it("never reaches past the ramp it has", () => {
    // The donut this replaced read `var(--lf-chart-6)`, a token that does not
    // exist, so a portfolio with six or more slices handed recharts an invalid
    // fill. Ranks now saturate at the last defined step.
    const many = Array.from({ length: 9 }, (_, i) => slice(`S${i}`, 11, 11_000));
    const { container } = render(<AllocationChart title="By asset" slices={many} currency="USD" />);
    const ranks = bar(container).map((s) => Number(s.rank));
    expect(Math.max(...ranks)).toBe(6);
    expect(ranks).toEqual([1, 2, 3, 4, 5, 6, 6, 6, 6]);
  });

  it("asks for prices rather than drawing a breakdown of nothing", () => {
    render(<AllocationChart title="By asset" slices={[]} currency="USD" />);
    expect(screen.getByText(/add prices to your holdings/i)).toBeInTheDocument();
    expect(document.querySelector(".lf-alloc-bar")).toBeNull();
  });
  it("does not skip a heading level under the page title", () => {
    // Hardcoded <h3> under the page's <h1>, while the sibling "Holdings"
    // section beside it was an <h2>. WCAG 1.3.1, and the route audit only
    // caught it once the page had data to render at all.
    render(<AllocationChart title="By asset" slices={SLICES} currency="USD" />);
    expect(screen.getByRole("heading", { level: 2, name: "By asset" })).toBeInTheDocument();
  });
});
