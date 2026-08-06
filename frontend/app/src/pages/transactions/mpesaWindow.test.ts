import { describe, expect, it } from "vitest";
import { countInWindow } from "./MpesaImportPanel";

/* The number this returns is printed on the import button, so it is a promise
   about what is going to happen. The cases below are the ones where a plausible
   implementation quietly breaks that promise. */
const BY_DAY = {
  "2026-05-10": 3,
  "2026-06-01": 5,
  "2026-06-30": 7,
  "2026-07-20": 11,
};

describe("countInWindow", () => {
  it("counts everything when no window is set", () => {
    expect(countInWindow(BY_DAY, "", "")).toBe(26);
  });

  it("includes both bounds", () => {
    // "1 June to 30 June" means the whole of both days. An exclusive end drops
    // the last day, which is the day someone catching up cares most about.
    expect(countInWindow(BY_DAY, "2026-06-01", "2026-06-30")).toBe(12);
  });

  it("treats a missing bound as unbounded rather than as a date", () => {
    expect(countInWindow(BY_DAY, "2026-06-01", "")).toBe(23);
    expect(countInWindow(BY_DAY, "", "2026-06-01")).toBe(8);
  });

  it("returns zero for a window with nothing in it", () => {
    expect(countInWindow(BY_DAY, "2026-09-01", "2026-09-30")).toBe(0);
  });

  it("returns zero when the bounds are inverted", () => {
    expect(countInWindow(BY_DAY, "2026-07-01", "2026-06-01")).toBe(0);
  });

  it("compares dates correctly across a month and year boundary", () => {
    // Lexicographic comparison on YYYY-MM-DD is only safe because the format
    // sorts like the dates do — zero-padded, most significant first.
    const spanning = { "2025-12-31": 2, "2026-01-01": 4, "2026-02-01": 8 };
    expect(countInWindow(spanning, "2026-01-01", "2026-01-31")).toBe(4);
    expect(countInWindow(spanning, "2025-12-31", "2026-01-01")).toBe(6);
  });

  it("handles an empty statement", () => {
    expect(countInWindow({}, "2026-01-01", "2026-12-31")).toBe(0);
  });
});
