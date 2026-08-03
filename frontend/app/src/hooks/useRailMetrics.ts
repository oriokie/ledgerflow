import { useBills, useNetWorthBase, useReviewCount } from "./useFinance";
import { useGoals } from "./useGoals";
import { useSuggestions } from "./useIntelligence";
import type { NavItemV2 } from "../components/shell/navConfigV2";

export interface RailMetric {
  /** Rendered beside the nav label. `null` while unknown — never a zero. */
  text: string | null;
  /** Spoken form, because "39.1k" beside "Accounts" is not a sentence. */
  label?: string;
  tone?: "attention";
}

/** 1_250 → "1.3k". A rail is ~90px of usable width; a full ledger amount does
 * not fit and truncating money is worse than rounding it. */
function compact(minor: number): string {
  const n = Math.abs(minor) / 100;
  const sign = minor < 0 ? "-" : "";
  if (n >= 1_000_000) return `${sign}${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${sign}${(n / 1_000).toFixed(1)}k`;
  return `${sign}${Math.round(n)}`;
}

/**
 * The live values the rail carries.
 *
 * The highest-leverage navigation change available, and nearly free: a rail
 * item that shows its own headline figure answers most questions *without
 * navigating at all*. The data is already in the React Query cache for the
 * dashboard, so on a warm cache this costs nothing but a render.
 *
 * `enabled` gates every request, so a user on the old navigation pays nothing
 * for a rail they cannot see.
 *
 * Every value here is deliberately absent rather than zero while it is
 * unknown. A rail that reads "Plan 0" when bills simply haven't loaded is
 * making a claim about the user's week that it cannot support — the same
 * missing-is-not-zero rule the Debt and Investments screens were rebuilt
 * around in Phase 4.
 */
export function useRailMetrics(enabled: boolean): Record<string, RailMetric> {
  const netWorth = useNetWorthBase();
  // 7 days: "this week" is the horizon a rail badge can usefully compress.
  const bills = useBills(enabled ? { upcoming: 7, status: "unpaid" } : {});
  const goals = useGoals();
  const suggestions = useSuggestions("pending", enabled);
  const review = useReviewCount(enabled);

  if (!enabled) return {};

  const out: Record<string, RailMetric> = {};

  const nw = netWorth.data;
  if (nw) {
    out.netWorth = {
      text: compact(nw.total_minor),
      label: `Net worth ${compact(nw.total_minor)} ${nw.base_currency}`,
    };
  }

  const due = bills.data?.length ?? null;
  if (due !== null && due > 0) {
    out.dueThisWeek = {
      text: String(due),
      label: `${due} ${due === 1 ? "bill" : "bills"} due in the next 7 days`,
      tone: "attention",
    };
  }

  const active = (goals.data ?? []).filter((g) => g.status === "active");
  if (active.length > 0) {
    const pct = Math.round(active.reduce((sum, g) => sum + g.percent, 0) / active.length);
    out.goalProgress = { text: `${pct}%`, label: `Goals ${pct}% of target on average` };
  }

  const needsReview = review.data?.count ?? null;
  if (needsReview !== null && needsReview > 0) {
    out.unreviewed = {
      text: String(needsReview),
      label: `${needsReview} ${needsReview === 1 ? "transaction needs" : "transactions need"} a look`,
      tone: "attention",
    };
  }

  const open = suggestions.data?.length ?? null;
  if (open !== null && open > 0) {
    out.openSuggestions = {
      text: String(open),
      label: `${open} ${open === 1 ? "suggestion" : "suggestions"} waiting`,
      tone: "attention",
    };
  }

  return out;
}

export function metricFor(
  item: NavItemV2,
  metrics: Record<string, RailMetric>,
): RailMetric | undefined {
  return item.metric ? metrics[item.metric] : undefined;
}
