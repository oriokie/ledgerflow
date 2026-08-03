import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTheme } from "./useTheme";

// jsdom has no matchMedia — provide a stub defaulting to "light".
function stubMatchMedia(prefersDark = false) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: prefersDark && query.includes("dark"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  stubMatchMedia(false);
});

afterEach(() => vi.unstubAllGlobals());

describe("useTheme", () => {
  it("defaults to 'system' when nothing is stored", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("system");
  });

  it("reads an explicit stored preference", () => {
    localStorage.setItem("lf-theme", "dark");
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("dark");
  });

  it("persists an explicit choice and sets data-theme", () => {
    const { result } = renderHook(() => useTheme());

    act(() => result.current.setTheme("dark"));
    expect(localStorage.getItem("lf-theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");

    act(() => result.current.setTheme("light"));
    expect(localStorage.getItem("lf-theme")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("");
  });

  it("removes the stored key when switching back to 'system'", () => {
    localStorage.setItem("lf-theme", "dark");
    const { result } = renderHook(() => useTheme());

    act(() => result.current.setTheme("system"));
    expect(localStorage.getItem("lf-theme")).toBeNull();
  });

  it("resolves 'system' to the OS preference", () => {
    stubMatchMedia(true); // OS prefers dark
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("system");
    expect(result.current.resolved).toBe("dark");
  });
});
