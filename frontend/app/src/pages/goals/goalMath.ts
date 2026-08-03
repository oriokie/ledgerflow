import type { SavingsGoal } from "../../api/types";

/** The milestone checkpoints every goal is tracked against. */
export const MILESTONES = [25, 50, 75, 100] as const;

export interface MilestoneMark {
  pct: number;
  reached: boolean;
  amountMinor: number;
}

/** The four milestones for a goal, each with the amount it represents and
 * whether it's been reached yet. */
export function milestones(goal: Pick<SavingsGoal, "target_minor" | "percent">): MilestoneMark[] {
  return MILESTONES.map((pct) => ({
    pct,
    reached: goal.percent >= pct,
    amountMinor: Math.round((goal.target_minor * pct) / 100),
  }));
}

/** The next milestone still ahead, or null once the goal is complete. */
export function nextMilestone(goal: Pick<SavingsGoal, "target_minor" | "percent">): MilestoneMark | null {
  return milestones(goal).find((m) => !m.reached) ?? null;
}

/** How much more to save to hit the next milestone (0 when there's none left). */
export function amountToNextMilestone(goal: Pick<SavingsGoal, "target_minor" | "percent" | "saved_minor">): number {
  const next = nextMilestone(goal);
  return next ? Math.max(0, next.amountMinor - goal.saved_minor) : 0;
}

export interface GoalTotals {
  currency: string;
  saved_minor: number;
  target_minor: number;
  percent: number;
  activeCount: number;
  achievedCount: number;
}

/**
 * A motivating headline across all live goals: how much saved toward how much,
 * and how many goals are done. Money totals use the most common currency (goals
 * can be in different currencies); counts span all live goals.
 */
export function goalTotals(goals: SavingsGoal[] | undefined): GoalTotals {
  const live = (goals ?? []).filter((g) => g.status !== "archived");
  const counts = new Map<string, number>();
  for (const g of live) counts.set(g.currency, (counts.get(g.currency) ?? 0) + 1);
  const currency = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "USD";

  let saved = 0;
  let target = 0;
  for (const g of live) {
    if (g.currency !== currency) continue;
    saved += g.saved_minor;
    target += g.target_minor;
  }
  return {
    currency,
    saved_minor: saved,
    target_minor: target,
    percent: target > 0 ? (saved / target) * 100 : 0,
    activeCount: live.length,
    achievedCount: live.filter((g) => g.is_met).length,
  };
}

/** Goals in a motivating order: in-progress first (nearest completion leading),
 * achieved goals last. */
export function sortGoals(goals: SavingsGoal[]): SavingsGoal[] {
  return [...goals].sort((a, b) => {
    const metA = a.is_met ? 1 : 0;
    const metB = b.is_met ? 1 : 0;
    if (metA !== metB) return metA - metB;
    return b.percent - a.percent || a.name.localeCompare(b.name);
  });
}
