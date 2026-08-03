import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { findViolations, describeViolations } from "../test/a11y";
import { Meter } from "./Meter";

describe("Meter accessibility", () => {
  it("takes its accessible name from a plain string label", () => {
    // Most call sites already pass a visible string label; reusing it means
    // they get a named progressbar without repeating themselves.
    render(<Meter value={40} label="Budget used" />);
    expect(screen.getByRole("progressbar", { name: "Budget used" })).toBeInTheDocument();
  });

  it("accepts an explicit aria-label when the visible label is a ReactNode", () => {
    render(
      <Meter
        value={40}
        aria-label="Emergency fund progress"
        label={<span>Emergency fund <b>Met</b></span>}
      />,
    );
    expect(screen.getByRole("progressbar", { name: "Emergency fund progress" })).toBeInTheDocument();
  });

  it("prefers an explicit aria-label over the visible label", () => {
    render(<Meter value={40} label="Short" aria-label="A more precise description" />);
    expect(screen.getByRole("progressbar", { name: "A more precise description" })).toBeInTheDocument();
  });

  it("announces a string caption as the value text", () => {
    // "72% of income kept" is far more use to a screen reader than "72".
    render(<Meter value={72} label="Savings rate" caption="72% of income kept" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuetext", "72% of income kept");
  });

  it("has no axe violations when named", async () => {
    const { container } = render(<Meter value={40} label="Budget used" caption="40%" />);
    const violations = await findViolations(container);
    expect(violations, describeViolations(violations)).toHaveLength(0);
  });

  it("still clamps out-of-range values", () => {
    render(<Meter value={150} label="Over" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });
});
