import { AlertTriangle, Hourglass, ShieldCheck, TrendingDown } from "lucide-react";
import type { CashRunway } from "../../api/types";
import { formatAmount, formatDateLong } from "../../lib/money";
import { Card } from "../../ui";

const TONES: Record<string, { color: string; bg: string }> = {
  healthy: { color: "var(--lf-status-success)", bg: "color-mix(in srgb, var(--lf-status-success) 10%, transparent)" },
  watch: { color: "var(--lf-status-info, var(--lf-text-link))", bg: "var(--lf-selection-bg)" },
  warning: { color: "var(--lf-status-warning)", bg: "color-mix(in srgb, var(--lf-status-warning) 12%, transparent)" },
  critical: { color: "var(--lf-status-danger)", bg: "color-mix(in srgb, var(--lf-status-danger) 10%, transparent)" },
};

function headline(r: CashRunway): string {
  if (r.status === "insufficient_data")
    return "Not enough history yet to project your cash";
  if (r.status === "healthy")
    return r.months_of_runway == null
      ? "You're adding cash every month — no run-out in sight"
      : "Your cash comfortably covers the year ahead";
  if (r.status === "watch") return `About ${r.months_of_runway} months of cash at the current pace`;
  if (r.status === "warning") return `Heads up — roughly ${r.months_of_runway} months of cash left`;
  return r.projected_runout_date
    ? `At this pace you could run out of cash around ${formatDateLong(r.projected_runout_date)}`
    : "Upcoming bills exceed your available cash";
}

function detail(r: CashRunway): string | null {
  if (r.status === "insufficient_data")
    return "Log a couple of months of income and spending and this projection switches on.";
  const parts: string[] = [];
  if (r.currency && r.liquid_balance_minor != null)
    parts.push(`Liquid today: ${formatAmount(r.liquid_balance_minor, r.currency)}`);
  if (r.currency && r.avg_monthly_net_minor != null)
    parts.push(
      `avg net ${r.avg_monthly_net_minor >= 0 ? "+" : ""}${formatAmount(r.avg_monthly_net_minor, r.currency)}/mo over ${r.months_analyzed} months`,
    );
  if (r.currency && r.upcoming_bills_count)
    parts.push(`${r.upcoming_bills_count} bill${r.upcoming_bills_count === 1 ? "" : "s"} (${formatAmount(r.upcoming_bills_minor ?? 0, r.currency)}) due within 30 days`);
  return parts.length ? parts.join(" · ") : null;
}

/**
 * The question every budget app dodges, answered plainly: will you run out of
 * cash, and when? Combines today's liquid balance, the 3-month net-flow trend,
 * and the next 30 days of bills.
 */
export function CashRunwayCard({ runway }: { runway: CashRunway | undefined }) {
  if (!runway) return null;
  const tone = TONES[runway.status] ?? TONES.watch;
  const Icon =
    runway.status === "critical"
      ? TrendingDown
      : runway.status === "warning"
        ? AlertTriangle
        : runway.status === "insufficient_data"
          ? Hourglass
          : ShieldCheck;
  const sub = detail(runway);

  return (
    <Card eyebrow="Cash runway" data-testid="cash-runway" style={{ borderLeft: `3px solid ${tone.color}` }}>
      <div style={{ display: "flex", gap: "var(--lf-space-3)", alignItems: "flex-start" }}>
        <span
          aria-hidden="true"
          style={{
            display: "inline-flex",
            padding: 8,
            borderRadius: "var(--lf-radius-md)",
            background: tone.bg,
            color: tone.color,
            flexShrink: 0,
          }}
        >
          <Icon size={18} strokeWidth={2} />
        </span>
        <div>
          <p style={{ fontWeight: "var(--lf-weight-semibold)", color: "var(--lf-text-primary)" }}>{headline(runway)}</p>
          {sub && (
            <p className="lf-text-sm lf-text-secondary" style={{ marginTop: 4 }}>
              {sub}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
