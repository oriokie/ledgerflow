import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useProductIdentity } from "./useProductIdentity";

afterEach(() => delete document.documentElement.dataset.product);

describe("product identity", () => {
  it("marks the document while the shell is mounted", () => {
    renderHook(() => useProductIdentity("platform"));
    expect(document.documentElement.dataset.product).toBe("platform");
  });

  it("clears on unmount, so leaving the console leaves its palette behind", () => {
    // Without this, an operator who returns to their own workspace keeps the
    // control room's colours — which inverts the point of having two
    // identities, since now the customer app is the one in disguise.
    const { unmount } = renderHook(() => useProductIdentity("platform"));
    unmount();
    expect(document.documentElement.dataset.product).toBeUndefined();
  });

  it("does nothing when there is no identity to apply", () => {
    renderHook(() => useProductIdentity(null));
    expect(document.documentElement.dataset.product).toBeUndefined();
  });
});
