/** Shared recharts axis/grid theming and a compact number formatter.
 * Kept component-free so it can sit beside the tooltip component without
 * tripping fast-refresh's single-export-kind rule. */

/**
 * Axis-tick size, in px, paired to `--lf-text-xs`.
 *
 * Recharts renders `fontSize` on an axis as an SVG presentation attribute, so
 * `var(--lf-text-xs)` never resolves there — it has to be a number. That is why
 * eight chart call sites had a bare `12` (and one an `11`), which was the last
 * off-scale type value left in the product once the ledger-cents rule was
 * fixed.
 *
 * A number that has to match a token is a pairing that will drift, so
 * `chartTheme.test.ts` parses `tokens.css` and fails if the two disagree.
 *
 * Where recharts takes a *style object* instead — `wrapperStyle`,
 * `contentStyle` — use `var(--lf-text-xs)` directly; those are real CSS.
 */
export const CHART_TICK_FONT_PX = 11.1;

export const AXIS_TICK: { fontSize: number; fill: string } = {
  fontSize: CHART_TICK_FONT_PX,
  fill: "var(--lf-text-tertiary)",
};

export const axisLineProps = {
  stroke: "var(--lf-border-subtle)",
  tickLine: false,
} as const;

export const gridProps = {
  strokeDasharray: "3 3",
  stroke: "var(--lf-border-subtle)",
  vertical: false,
} as const;

/** Compact currency for axis ticks: 1_250 → "1.3k", 2_400_000 → "2.4M". */
export function compactNumber(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return `${Math.round(n)}`;
}
