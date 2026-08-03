import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { AXIS_TICK, CHART_TICK_FONT_PX, compactNumber } from "./chartTheme";

// Resolved from the package root rather than `import.meta.url`: under jsdom
// that is not a file: URL, so `fileURLToPath` throws. Vitest always runs with
// the package as its working directory.
const TOKENS = resolve(process.cwd(), "src/styles/tokens.css");

/** `--lf-text-xs: 0.694rem;` → 11.104 */
function tokenPx(name: string): number {
  const css = readFileSync(TOKENS, "utf8");
  const match = new RegExp(`--lf-text-${name}:\\s*([0-9.]+)rem`).exec(css);
  if (!match) throw new Error(`--lf-text-${name} not found in tokens.css`);
  return Number(match[1]) * 16;
}

describe("chart typography", () => {
  it("keeps the axis-tick size paired to --lf-text-xs", () => {
    // Recharts renders `fontSize` on an axis as an SVG presentation attribute,
    // so `var(--lf-text-xs)` cannot be used there and the value has to be a
    // literal number. A literal that must match a token is a pairing that
    // drifts — eight chart call sites had drifted to a bare 12, which was the
    // last off-scale type value in the product. This is the thing that stops
    // it happening again.
    expect(CHART_TICK_FONT_PX).toBeCloseTo(tokenPx("xs"), 1);
  });

  it("uses that size for axis ticks", () => {
    expect(AXIS_TICK.fontSize).toBe(CHART_TICK_FONT_PX);
  });

  it("keeps axis ticks on token colours", () => {
    expect(AXIS_TICK.fill).toMatch(/^var\(--lf-/);
  });
});

describe("compactNumber", () => {
  it("shortens thousands and millions for axis labels", () => {
    expect(compactNumber(1250)).toBe("1.3k");
    expect(compactNumber(2_400_000)).toBe("2.4M");
    expect(compactNumber(-1500)).toBe("-1.5k");
  });

  it("leaves small numbers alone", () => {
    expect(compactNumber(940)).toBe("940");
    expect(compactNumber(0)).toBe("0");
  });
});
