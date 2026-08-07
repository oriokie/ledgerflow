import { describe, expect, it } from "vitest";
import { CURRENCIES, CURRENCY_OPTIONS } from "./currencies";

describe("currency catalog", () => {
  it("covers major + emerging-market currencies with correct minor units", () => {
    const codes = new Set(CURRENCIES.map((c) => c.code));
    expect(codes.has("USD") && codes.has("EUR") && codes.has("KES")).toBe(true);
    expect(CURRENCIES.find((c) => c.code === "JPY")?.digits).toBe(0);
    expect(CURRENCIES.find((c) => c.code === "KWD")?.digits).toBe(3);
    // Options are select-ready and unique.
    expect(CURRENCY_OPTIONS[0]).toHaveProperty("value");
    expect(new Set(CURRENCY_OPTIONS.map((o) => o.value)).size).toBe(CURRENCY_OPTIONS.length);
  });
});
