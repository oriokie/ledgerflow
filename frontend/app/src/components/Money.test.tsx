import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Money } from "./Money";

function stub(el: HTMLElement, prop: "scrollWidth" | "clientWidth", value: number) {
  Object.defineProperty(el, prop, { configurable: true, value });
}

// See src/lib/useFitFontSize.test.tsx for why getComputedStyle needs a stub
// in jsdom — no layout engine, no real style cascade.
function stubComputedFontSize(px: number) {
  return vi
    .spyOn(window, "getComputedStyle")
    .mockImplementation(() => ({ fontSize: `${px}px` }) as CSSStyleDeclaration);
}

afterEach(() => vi.restoreAllMocks());

describe("Money", () => {
  it("renders the whole and cents parts", () => {
    render(<Money amountMinor={125099} currency="USD" />);
    expect(screen.getByText("$1,250")).toBeInTheDocument();
    expect(screen.getByText(".99")).toBeInTheDocument();
  });

  it("a hero amount shrinks to fit when it overflows its parent", () => {
    stubComputedFontSize(32);
    const { rerender, container } = render(<Money amountMinor={125099} currency="USD" hero />);
    const target = container.querySelector("data")!;
    const parent = target.parentElement!;
    stub(target, "scrollWidth", 200);
    stub(parent as HTMLElement, "clientWidth", 160);

    // A dep (amountMinor) change re-triggers the hook's effect.
    rerender(<Money amountMinor={125098} currency="USD" hero />);
    expect((target as HTMLElement).style.fontSize).toBe("25.6px"); // 32 * (160/200)
  });

  it("a non-hero amount is never measured for shrinking", () => {
    stubComputedFontSize(32);
    const { rerender, container } = render(<Money amountMinor={125099} currency="USD" />);
    const target = container.querySelector("data")!;
    const parent = target.parentElement!;
    stub(target, "scrollWidth", 320);
    stub(parent as HTMLElement, "clientWidth", 160);

    rerender(<Money amountMinor={125098} currency="USD" />);
    expect((target as HTMLElement).style.fontSize).toBe("");
  });
});
