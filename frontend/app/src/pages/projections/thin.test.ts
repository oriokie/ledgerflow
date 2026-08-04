import { describe, expect, it } from "vitest";
import { thin } from "./thin";

describe("thin", () => {
  it("leaves a short series untouched", () => {
    const points = [1, 2, 3];
    expect(thin(points, 120)).toBe(points);
  });

  it("downsamples a forty-year projection to something drawable", () => {
    const points = Array.from({ length: 480 }, (_, i) => i);
    const result = thin(points, 120);
    expect(result.length).toBeLessThanOrEqual(121);
    expect(result[0]).toBe(0);
  });

  it("always keeps the final point", () => {
    // 480 thinned by a step of 4 lands exactly on the last index; 481 does not,
    // and that off-by-one is what would silently shorten the line.
    for (const length of [480, 481, 300, 137]) {
      const points = Array.from({ length }, (_, i) => i);
      const result = thin(points, 120);
      expect(result[result.length - 1]).toBe(length - 1);
    }
  });

  it("preserves order", () => {
    const points = Array.from({ length: 400 }, (_, i) => i);
    const result = thin(points, 50);
    const sorted = [...result].sort((a, b) => a - b);
    expect(result).toEqual(sorted);
  });
});
