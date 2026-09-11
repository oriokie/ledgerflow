import { describe, expect, it } from "vitest";
import {
  CURRENCIES,
  CURRENCY_OPTIONS,
  FALLBACK_CURRENCY,
  pickPreferredCurrency,
  workspaceCurrency,
} from "./currencies";

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

describe("workspace currency", () => {
  it("reads the tenant base and never invents KES", () => {
    expect(workspaceCurrency({ base_currency: "KES" })).toBe("KES");
    expect(workspaceCurrency({ base_currency: "USD" })).toBe("USD");
    expect(workspaceCurrency(null)).toBe(FALLBACK_CURRENCY);
  });

  it("prefers the workspace books when that code is in the data", () => {
    expect(pickPreferredCurrency("KES", ["USD", "KES"])).toBe("KES");
    expect(pickPreferredCurrency("KES", ["USD", "EUR"])).toBe("USD");
    expect(pickPreferredCurrency("KES", [])).toBe("KES");
  });
});
