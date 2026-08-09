import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useFitFontSize } from "./useFitFontSize";

function TestBox({ active, dep }: { active: boolean; dep: number }) {
  const ref = useFitFontSize<HTMLDivElement>(active, [dep]);
  return (
    <div data-testid="parent">
      <div ref={ref} data-testid="target">
        content
      </div>
    </div>
  );
}

function stub(el: HTMLElement, prop: "scrollWidth" | "clientWidth", value: number) {
  Object.defineProperty(el, prop, { configurable: true, value });
}

/**
 * jsdom has no layout engine (scrollWidth/clientWidth always read 0) and no
 * real style cascade — the hook deliberately clears the target's own inline
 * font-size before every measurement (so a previous shrink never compounds),
 * which leaves jsdom nothing to resolve a "base" size from on its own. This
 * stubs the platform API directly, the way a real browser's resolved
 * font-size would come back.
 */
function stubComputedFontSize(px: number) {
  return vi
    .spyOn(window, "getComputedStyle")
    .mockImplementation(() => ({ fontSize: `${px}px` }) as CSSStyleDeclaration);
}

afterEach(() => vi.restoreAllMocks());

describe("useFitFontSize", () => {
  it("shrinks proportionally when content overflows", () => {
    stubComputedFontSize(20);
    const { rerender, getByTestId } = render(<TestBox active dep={0} />);
    const target = getByTestId("target");
    const parent = getByTestId("parent");
    stub(target, "scrollWidth", 125);
    stub(parent, "clientWidth", 100);

    rerender(<TestBox active dep={1} />);
    expect(target.style.fontSize).toBe("16px"); // 20 * (100/125)
  });

  it("never shrinks past the 0.6 floor", () => {
    stubComputedFontSize(20);
    const { rerender, getByTestId } = render(<TestBox active dep={0} />);
    const target = getByTestId("target");
    const parent = getByTestId("parent");
    stub(target, "scrollWidth", 1000);
    stub(parent, "clientWidth", 100);

    rerender(<TestBox active dep={1} />);
    expect(target.style.fontSize).toBe("12px"); // 20 * 0.6 floor, not 20 * (100/1000)
  });

  it("no-ops when content already fits", () => {
    stubComputedFontSize(20);
    const { rerender, getByTestId } = render(<TestBox active dep={0} />);
    const target = getByTestId("target");
    const parent = getByTestId("parent");
    stub(target, "scrollWidth", 80);
    stub(parent, "clientWidth", 100);

    rerender(<TestBox active dep={1} />);
    expect(target.style.fontSize).toBe("");
  });

  it("no-ops entirely when active is false", () => {
    stubComputedFontSize(20);
    const { rerender, getByTestId } = render(<TestBox active={false} dep={0} />);
    const target = getByTestId("target");
    const parent = getByTestId("parent");
    stub(target, "scrollWidth", 1000);
    stub(parent, "clientWidth", 100);

    rerender(<TestBox active={false} dep={1} />);
    expect(target.style.fontSize).toBe("");
  });
});
