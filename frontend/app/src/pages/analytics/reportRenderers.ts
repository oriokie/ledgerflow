import type { ReportResult } from "../../api/types";

/** Palette for categorical charts, from the design tokens so it follows the
 * theme and matches every other chart in the product. */
export const CHART_COLORS = [
  "var(--lf-chart-1)",
  "var(--lf-chart-2)",
  "var(--lf-chart-3)",
  "var(--lf-chart-4)",
  "var(--lf-chart-5)",
  "var(--lf-chart-6)",
];

/** Keys that hold money in minor units, by convention across every report. */
export function isMoneyKey(key: string): boolean {
  return key.endsWith("_minor");
}

/** Human label for a report field.
 *
 * Derived from the key rather than a per-report lookup table: the reports
 * already use consistent names (`amount_minor`, `label`, `count`), so one rule
 * covers all fourteen and a new report needs no extra mapping.
 */
export function humanizeKey(key: string): string {
  const base = key.replace(/_minor$/, "").replace(/_pct$/, " %").replace(/_/g, " ");
  return base.charAt(0).toUpperCase() + base.slice(1);
}

/** The field a time series is plotted against.
 *
 * Reports name it `month`, `period` or `date` depending on granularity, so the
 * renderer looks for whichever is present rather than forcing one name on
 * reports that legitimately differ.
 */
export function timeKeyOf(rows: Record<string, unknown>[]): string | null {
  if (rows.length === 0) return null;
  for (const candidate of ["month", "period", "date", "as_of", "occurred_on"]) {
    if (candidate in rows[0]) return candidate;
  }
  return null;
}

/** Numeric fields worth plotting, excluding the time axis and any identifier.
 *
 * Percentages are excluded from money charts because plotting 92.5 alongside
 * 400000 makes the percentage invisible and the scale meaningless. */
export function numericKeys(
  rows: Record<string, unknown>[],
  { exclude = [] as string[] } = {},
): string[] {
  if (rows.length === 0) return [];
  return Object.keys(rows[0]).filter(
    (key) =>
      typeof rows[0][key] === "number" &&
      !key.endsWith("_id") &&
      !exclude.includes(key),
  );
}

/** Short axis label for a time value. */
export function formatTimeLabel(value: unknown): string {
  if (typeof value !== "string") return String(value ?? "");
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

/** Whether a report carried a caveat the reader needs.
 *
 * Reports flag partial months, insufficient history and the like in `meta`;
 * surfacing those is what stops a half-month being read as a collapse in
 * spending. */
export function caveatsOf(result: ReportResult): string[] {
  const out: string[] = [];
  const meta = result.meta ?? {};
  if (meta.partial_month) out.push("This month isn't over yet, so it's not directly comparable.");
  if (meta.insufficient_history)
    out.push("Not enough history yet to show a reliable trend.");
  if (typeof meta.uncategorised_share === "number" && meta.uncategorised_share > 10)
    out.push(
      `${Math.round(meta.uncategorised_share)}% of spending isn't categorised, so the split is incomplete.`,
    );
  return out;
}
