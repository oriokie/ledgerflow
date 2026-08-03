import { describe, expect, it } from "vitest";
import { amountDirectionClass, formatAmount, formatAmountParts, formatAmountSigned, formatRelativeTime, majorToMinor, minorToMajor } from "./money";

describe("minor/major conversion", () => {
  it("converts minor units to major", () => {
    expect(minorToMajor(12345)).toBe(123.45);
    expect(minorToMajor(0)).toBe(0);
    expect(minorToMajor(-500)).toBe(-5);
  });

  it("converts major to minor with rounding (no float drift)", () => {
    expect(majorToMinor(123.45)).toBe(12345);
    // 19.99 * 100 is 1998.9999999 in float; must round to 1999.
    expect(majorToMinor(19.99)).toBe(1999);
    expect(majorToMinor(0.1 + 0.2)).toBe(30);
  });

  it("round-trips a value", () => {
    expect(minorToMajor(majorToMinor(87.65))).toBe(87.65);
  });
});

describe("formatAmountParts", () => {
  it("splits whole and cents, using the absolute value", () => {
    expect(formatAmountParts(12345, "USD")).toEqual({ whole: "$123", cents: ".45" });
    expect(formatAmountParts(-12345, "USD")).toEqual({ whole: "$123", cents: ".45" });
  });

  it("formats zero", () => {
    expect(formatAmountParts(0, "USD")).toEqual({ whole: "$0", cents: ".00" });
  });
});

describe("formatAmount", () => {
  it("recombines whole + cents", () => {
    expect(formatAmount(12345, "USD")).toBe("$123.45");
  });
});

describe("amountDirectionClass — the money color semantics", () => {
  it("transfers are muted regardless of sign", () => {
    expect(amountDirectionClass(500, true)).toBe("lf-amount--transfer");
    expect(amountDirectionClass(-500, true)).toBe("lf-amount--transfer");
  });

  it("positive is money-in, negative is money-out", () => {
    expect(amountDirectionClass(500, false)).toBe("lf-amount--in");
    expect(amountDirectionClass(-500, false)).toBe("lf-amount--out");
  });

  it("zero counts as money-in (not an error state)", () => {
    expect(amountDirectionClass(0, false)).toBe("lf-amount--in");
  });
});

describe("formatRelativeTime", () => {
  it("reports very recent times as 'just now'", () => {
    const t = new Date(Date.now() - 10_000).toISOString();
    expect(formatRelativeTime(t)).toBe("just now");
  });

  it("reports minutes and hours compactly", () => {
    expect(formatRelativeTime(new Date(Date.now() - 5 * 60_000).toISOString())).toBe("5m");
    expect(formatRelativeTime(new Date(Date.now() - 3 * 3_600_000).toISOString())).toBe("3h");
  });

  it("reports days within a week", () => {
    expect(formatRelativeTime(new Date(Date.now() - 2 * 86_400_000).toISOString())).toBe("2d");
  });

  it("returns empty string for an invalid date", () => {
    expect(formatRelativeTime("not-a-date")).toBe("");
  });
});


describe("formatAmountSigned — for standalone text", () => {
  it("keeps the minus sign that formatAmount deliberately drops", () => {
    // formatAmount returns the magnitude because <Money> renders direction as
    // a separate visual treatment. Used as bare text — an aria-label, a chart
    // tooltip, a calendar cell — that turns a -$200 overdraft into a
    // comfortable "$200.00".
    expect(formatAmount(-20_000, "USD")).toBe("$200.00");
    expect(formatAmountSigned(-20_000, "USD")).toBe("-$200.00");
  });

  it("leaves positive and zero amounts unchanged", () => {
    expect(formatAmountSigned(20_000, "USD")).toBe("$200.00");
    expect(formatAmountSigned(0, "USD")).toBe("$0.00");
  });

  it("agrees with formatAmount on magnitude", () => {
    for (const minor of [-123_45, -1, 0, 1, 999_99]) {
      expect(formatAmountSigned(minor, "USD")).toContain(formatAmount(minor, "USD"));
    }
  });
});
