import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { readFlag, useFlag, writeFlag } from "./featureFlags";

afterEach(() => localStorage.clear());

describe("feature flags", () => {
  it("defaults off, so nobody gets an IA change they didn't ask for", () => {
    expect(readFlag("navV2")).toBe(false);
  });

  it("persists across reads", () => {
    writeFlag("navV2", true);
    expect(readFlag("navV2")).toBe(true);
    writeFlag("navV2", false);
    expect(readFlag("navV2")).toBe(false);
  });

  it("re-renders the tab that made the change", () => {
    // `storage` only fires in *other* tabs. Without the custom event, the
    // Settings switch would flip and the rail beside it would not move —
    // which reads as the setting not working.
    const { result } = renderHook(() => useFlag("navV2"));
    expect(result.current[0]).toBe(false);
    act(() => result.current[1](true));
    expect(result.current[0]).toBe(true);
  });

  it("stays usable when storage throws", () => {
    // Private mode and some embedded webviews throw on access rather than
    // returning null. A flag read must never be able to break the router.
    const original = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new Error("denied");
      },
    });
    expect(() => readFlag("navV2")).not.toThrow();
    expect(readFlag("navV2")).toBe(false);
    expect(() => writeFlag("navV2", true)).not.toThrow();
    if (original) Object.defineProperty(window, "localStorage", original);
  });
});
