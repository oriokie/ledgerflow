/**
 * Display formatters for the platform workspace.
 *
 * Kept out of the page modules so those export components only — a module that
 * mixes component and non-component exports breaks React Fast Refresh, and the
 * formatters are shared across every admin page anyway.
 */

/** Minor units → a localized currency string. Money is integer minor units
 * everywhere in this product, so every display goes through here. */
export function money(minor: number | null | undefined, currency = "USD"): string {
  if (minor === null || minor === undefined) return "—";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(minor / 100);
}

/** A 0–1 rate as a percentage. `null` renders as an em dash rather than "0.0%",
 * because "we could not compute this" and "this is zero" are different facts
 * and an operator will act differently on each. */
export function percent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "—";
  return `${(rate * 100).toFixed(1)}%`;
}

/** Byte count → a short human string. */
export function bytes(value: number): string {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}


/** `2025-09-01` -> `Sep 25`.
 *
 * The console's charts were plotting raw ISO dates as axis labels: ten
 * characters where three convey the same thing, which is what put a tick on
 * top of the Y axis' own "0". Long labels are a layout problem disguised as a
 * formatting one.
 */
export function monthTick(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

/** A timestamp → `3 Aug 2026`.
 *
 * Every admin table was calling bare `toLocaleDateString()`, which on a
 * US-locale machine renders `7/30/2026`: ambiguous against the `30/7/2026` a
 * European operator reads out of the same column, and inconsistent with the
 * `Jul 30` the customer-facing product shows for the same field. An explicit
 * month name removes the ambiguity in every locale.
 */
export function day(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** A timestamp → `3 Aug 2026, 18:02`.
 *
 * Bare `toLocaleString()` appended seconds (`6:02:20 PM`). No operator decision
 * on these screens turns on the second a row was written, and the extra digits
 * widen every timestamp column enough to cost a real one.
 */
export function moment(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Maps a status string to the Badge tone that represents it.
 *
 * Single source of truth for status → tone across the admin console. A
 * second, disagreeing copy of this mapping on the Tenants page was the
 * reason invoice badges there rendered gray regardless of the invoice's
 * real status — every admin screen must read status color off this one.
 */
export function tone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (["paid", "succeeded", "ok", "recovered", "active"].includes(status)) return "success";
  if (
    ["pending", "processing", "requested", "approved", "degraded", "open", "trialing", "incomplete"].includes(
      status,
    )
  )
    return "warning";
  if (
    [
      "failed",
      "overdue",
      "rejected",
      "down",
      "abandoned",
      "suspended",
      "past_due",
      "canceled",
      "cancelled",
    ].includes(status)
  )
    return "danger";
  return "neutral";
}

/** `card_declined` → `Card declined`.
 *
 * Provider and state machine codes were reaching the screen verbatim. They are
 * identifiers, not copy, and an operator reading `card_declined` in a Last
 * failure column is reading our database schema.
 */
export function humanize(code: string | null | undefined): string {
  if (!code) return "—";
  const words = code.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
