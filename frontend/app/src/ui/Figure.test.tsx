import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Figure, FigureRow } from "./Figure";

describe("Figure", () => {
  it("renders a money figure through the ledger treatment", () => {
    const { container } = render(<Figure label="Net worth" amountMinor={3914931} currency="KES" />);
    expect(screen.getByText("Net worth")).toBeInTheDocument();
    // `Money` owns the amount, so the ledger font and cents split stay in one place.
    expect(container.querySelector(".lf-amount")).toBeInTheDocument();
    expect(container.querySelector(".lf-amount-cents")).toHaveTextContent(".31");
  });

  it("renders a non-money value", () => {
    render(<Figure label="Achieved" value="0 of 2" />);
    expect(screen.getByText("0 of 2")).toBeInTheDocument();
  });

  it("keeps a negative amount signed", () => {
    const { container } = render(<Figure label="Net" amountMinor={-8126} currency="KES" />);
    // U+2212, not a hyphen: a shortfall must not read as a surplus.
    expect(container.querySelector(".lf-amount")?.textContent).toContain("−");
  });

  it("defaults to settled", () => {
    const { container } = render(<Figure label="Balance" amountMinor={100} currency="KES" />);
    expect(container.querySelector(".lf-figure")).toHaveAttribute("data-certainty", "settled");
  });

  it.each(["pending", "projected"] as const)("carries certainty %s onto the element", (certainty) => {
    const { container } = render(
      <Figure label="Rent" amountMinor={120000} currency="KES" certainty={certainty} />,
    );
    expect(container.querySelector(".lf-figure")).toHaveAttribute("data-certainty", certainty);
  });

  describe("speculative", () => {
    it("marks the value, flags it, and shows the confidence statement", () => {
      const { container } = render(
        <Figure
          label="Debt health"
          value="100"
          certainty="speculative"
          confidence="Based on 45% of the usual inputs."
        />,
      );
      expect(container.querySelector(".lf-figure")).toHaveAttribute("data-certainty", "speculative");
      expect(screen.getByText("Provisional")).toBeInTheDocument();
      expect(screen.getByText("Based on 45% of the usual inputs.")).toBeInTheDocument();
      // The tilde is decoration for assistive tech — "Provisional" carries it there.
      expect(container.querySelector(".lf-figure-value")?.textContent).toContain("~");
      expect(container.querySelector('[aria-hidden="true"]')).toHaveTextContent("~");
    });

    it("cannot be constructed without its caveat", () => {
      // The guarantee is at the type level, which is where it belongs: this is
      // what makes the Debt page's "100 / Excellent" from 45% of the inputs
      // unrepresentable rather than merely discouraged.
      // @ts-expect-error — `confidence` is required when certainty is speculative
      const invalid = <Figure label="Score" value="100" certainty="speculative" />;
      expect(invalid).toBeTruthy();
    });
  });

  it("renders hint and delta alongside the value", () => {
    render(
      <Figure label="Lowest point" amountMinor={4228381} currency="KES" hint="on Aug 2" delta="▲ 12%" />,
    );
    expect(screen.getByText("on Aug 2")).toBeInTheDocument();
    expect(screen.getByText("▲ 12%")).toBeInTheDocument();
  });

  it("applies tone only when asked", () => {
    const { container: plain } = render(<Figure label="Net" value="0" />);
    expect(plain.querySelector(".lf-figure")).toHaveAttribute("data-tone", "default");
    const { container: warned } = render(<Figure label="Net" value="0" tone="critical" />);
    expect(warned.querySelector(".lf-figure")).toHaveAttribute("data-tone", "critical");
  });

  it("labels every figure — a bare number is not a figure", () => {
    // Guards the one rule that makes the component worth having: the 71
    // selectors it replaces included values rendered with no label at all.
    const { container } = render(<Figure label="Income" amountMinor={0} currency="KES" />);
    expect(container.querySelector(".lf-figure-label")).not.toBeEmptyDOMElement();
  });
});

describe("FigureRow", () => {
  it("groups figures on one grid", () => {
    const { container } = render(
      <FigureRow>
        <Figure label="Assets" amountMinor={4228381} currency="KES" />
        <Figure label="Liabilities" amountMinor={313450} currency="KES" />
      </FigureRow>,
    );
    expect(container.querySelectorAll(".lf-figure")).toHaveLength(2);
    expect(container.querySelector(".lf-figure-row")).toBeInTheDocument();
  });

  it("marks a lead column when the first figure is the hero", () => {
    const { container } = render(
      <FigureRow lead>
        <Figure label="Net worth" size="hero" amountMinor={3914931} currency="KES" />
      </FigureRow>,
    );
    expect(container.querySelector(".lf-figure-row")).toHaveAttribute("data-lead", "true");
  });
});
