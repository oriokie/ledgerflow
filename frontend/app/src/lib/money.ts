/**
 * Every amount in the API is an integer in the currency's minor unit
 * (cents), never a float — this is the one conversion boundary in the app.
 * `formatAmountParts` splits into whole/cents so components can render the
 * signature `<span class="lf-amount-cents">` treatment from the design
 * system (large integer part, small decimal).
 */

export function minorToMajor(amountMinor: number): number {
  return amountMinor / 100;
}

export function majorToMinor(amountMajor: number): number {
  return Math.round(amountMajor * 100);
}

export function formatAmountParts(amountMinor: number, currency: string): { whole: string; cents: string } {
  const major = Math.abs(minorToMajor(amountMinor));
  const formatted = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    currencyDisplay: "narrowSymbol",
  }).format(major);
  const dot = formatted.lastIndexOf(".");
  if (dot === -1) return { whole: formatted, cents: "" };
  return { whole: formatted.slice(0, dot), cents: formatted.slice(dot) };
}

export function formatAmount(amountMinor: number, currency: string): string {
  const { whole, cents } = formatAmountParts(amountMinor, currency);
  return whole + cents;
}

/**
 * Like `formatAmount`, but keeps the minus sign.
 *
 * `formatAmount` deliberately returns the magnitude, because the `Money`
 * component renders direction as a separate visual treatment. That makes it
 * wrong for any *standalone text* use — an aria-label, a chart tooltip, a bare
 * cell — where dropping the sign turns a projected overdraft of -$200 into a
 * comfortable "$200.00". Use this wherever the string stands alone.
 */
export function formatAmountSigned(amountMinor: number, currency: string): string {
  const magnitude = formatAmount(amountMinor, currency);
  return amountMinor < 0 ? `-${magnitude}` : magnitude;
}

/** Design-system money semantics: money-in is verdant (highlighted event),
 * money-out is plain ink (normal life, not an error), transfers are muted. */
export function amountDirectionClass(amountMinor: number, isTransfer: boolean): string {
  if (isTransfer) return "lf-amount--transfer";
  return amountMinor >= 0 ? "lf-amount--in" : "lf-amount--out";
}

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(new Date(iso));
}

export function formatDateLong(iso: string): string {
  return new Intl.DateTimeFormat("en-US", { month: "long", day: "numeric", year: "numeric" }).format(
    new Date(iso),
  );
}

/** Compact relative time for notification timestamps ("just now", "3h", "2d").
 * Falls back to an absolute short date beyond a week. */
export function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.round((Date.now() - then) / 1000);
  if (secs < 45) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d`;
  return formatDate(iso);
}
