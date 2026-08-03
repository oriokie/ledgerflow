import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { isPinned, readPins, suggestLabel, usePinnedViews } from "./pinnedViews";

afterEach(() => localStorage.clear());

describe("pinned views", () => {
  it("starts empty and persists what is pinned", () => {
    const { result } = renderHook(() => usePinnedViews());
    expect(result.current.pins).toEqual([]);
    act(() => result.current.pin("Groceries this month", "/activity?category=food"));
    expect(readPins()).toHaveLength(1);
    expect(readPins()[0].label).toBe("Groceries this month");
  });

  it("treats the same URL as the same view", () => {
    const { result } = renderHook(() => usePinnedViews());
    act(() => result.current.pin("A", "/activity?q=x"));
    act(() => result.current.pin("A again", "/activity?q=x"));
    expect(result.current.pins).toHaveLength(1);
    expect(isPinned(result.current.pins, "/activity?q=x")).toBe(true);
    expect(isPinned(result.current.pins, "/activity")).toBe(false);
  });

  it("unpins", () => {
    const { result } = renderHook(() => usePinnedViews());
    act(() => result.current.pin("A", "/plan?tab=bills"));
    act(() => result.current.unpin("/plan?tab=bills"));
    expect(result.current.pins).toEqual([]);
  });

  it("caps the list, because a rail of pins is a rail nobody scans", () => {
    const { result } = renderHook(() => usePinnedViews());
    for (let i = 0; i < 12; i++) act(() => result.current.pin(`P${i}`, `/activity?n=${i}`));
    expect(result.current.pins).toHaveLength(result.current.max);
    expect(result.current.full).toBe(true);
  });

  it("survives hand-edited or corrupt storage", () => {
    // The key is user-writable. A malformed pin must not be able to take down
    // the shell that renders the rail on every route.
    localStorage.setItem("lf-pinned-views", "not json");
    expect(readPins()).toEqual([]);
    localStorage.setItem("lf-pinned-views", '[{"id":1},{"label":"x"},null]');
    expect(readPins()).toEqual([]);
    // A relative or absolute-URL `to` would be an open redirect in a rail.
    localStorage.setItem("lf-pinned-views", '[{"id":"a","label":"x","to":"https://evil.test"}]');
    expect(readPins()).toEqual([]);
  });
});

describe("suggested names", () => {
  it("names a plain destination", () => {
    expect(suggestLabel("/activity")).toBe("Activity");
    expect(suggestLabel("/plan")).toBe("Plan");
  });

  it("says when a view is a filtered one", () => {
    expect(suggestLabel("/activity?category=abc")).toBe("Activity · filtered");
  });

  it("uses the tab when there is one", () => {
    expect(suggestLabel("/plan?tab=bills")).toBe("Plan · bills");
  });
});
