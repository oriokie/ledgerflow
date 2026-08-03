import { describe, expect, it } from "vitest";
import type { SavingsGoal } from "../../api/types";
import { amountToNextMilestone, goalTotals, milestones, nextMilestone, sortGoals } from "./goalMath";

function goal(over: Partial<SavingsGoal> = {}): SavingsGoal {
  const target = over.target_minor ?? 10000;
  const saved = over.saved_minor ?? 0;
  return {
    id: Math.random().toString(36).slice(2),
    name: "Goal",
    currency: "USD",
    target_minor: target,
    target_date: null,
    tracking: "manual",
    linked_account_id: null,
    status: "active",
    notes: "",
    saved_minor: saved,
    remaining_minor: Math.max(0, target - saved),
    percent: target > 0 ? Math.min(100, (saved / target) * 100) : 0,
    is_met: saved >= target,
    required_monthly_minor: null,
    kind: "custom",
    priority: 3,
    planned_monthly_minor: null,
    auto_contribute_enabled: false,
    auto_contribute_minor: null,
    auto_contribute_day: null,
    ...over,
  };
}

describe("milestones", () => {
  it("marks reached checkpoints and computes their amounts", () => {
    const marks = milestones(goal({ target_minor: 10000, percent: 60 }));
    expect(marks.map((m) => m.pct)).toEqual([25, 50, 75, 100]);
    expect(marks.map((m) => m.reached)).toEqual([true, true, false, false]);
    expect(marks.map((m) => m.amountMinor)).toEqual([2500, 5000, 7500, 10000]);
  });
});

describe("nextMilestone / amountToNextMilestone", () => {
  it("points at the next unreached checkpoint", () => {
    expect(nextMilestone(goal({ percent: 60 }))?.pct).toBe(75);
    expect(nextMilestone(goal({ percent: 100 }))).toBeNull();
  });

  it("computes how much more to reach it", () => {
    expect(amountToNextMilestone(goal({ target_minor: 10000, saved_minor: 6000, percent: 60 }))).toBe(1500);
    expect(amountToNextMilestone(goal({ target_minor: 10000, saved_minor: 10000, percent: 100 }))).toBe(0);
  });
});

describe("goalTotals", () => {
  it("aggregates the most-common currency and counts achievements", () => {
    const t = goalTotals([
      goal({ currency: "USD", target_minor: 10000, saved_minor: 10000 }), // met
      goal({ currency: "USD", target_minor: 20000, saved_minor: 5000 }),
      goal({ currency: "EUR", target_minor: 99999, saved_minor: 1 }),
    ]);
    expect(t.currency).toBe("USD");
    expect(t.saved_minor).toBe(15000); // USD only
    expect(t.target_minor).toBe(30000);
    expect(t.activeCount).toBe(3);
    expect(t.achievedCount).toBe(1);
  });

  it("ignores archived goals", () => {
    const t = goalTotals([goal({ status: "archived", saved_minor: 5000 }), goal({ saved_minor: 1000 })]);
    expect(t.activeCount).toBe(1);
  });
});

describe("sortGoals", () => {
  it("puts in-progress goals first (nearest completion leading), achieved last", () => {
    const a = goal({ name: "A", percent: 30, saved_minor: 3000 });
    const b = goal({ name: "B", percent: 80, saved_minor: 8000 });
    const done = goal({ name: "C", target_minor: 5000, saved_minor: 5000, percent: 100 });
    const sorted = sortGoals([a, done, b]);
    expect(sorted.map((g) => g.name)).toEqual(["B", "A", "C"]);
  });
});
