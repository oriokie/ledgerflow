import {
  Car,
  GraduationCap,
  Home,
  Landmark,
  Palmtree,
  PiggyBank,
  ShieldCheck,
  Target,
  type LucideIcon,
} from "lucide-react";
import type { GoalKind, GoalPriority } from "../../api/types";

/** Human labels for the goal taxonomy. Kept next to the icons so a new kind
 * can't be added in one place and forgotten in the other. */
export const GOAL_KIND_LABELS: Record<GoalKind, string> = {
  emergency_fund: "Emergency fund",
  vacation: "Vacation",
  house_deposit: "House deposit",
  education: "Education",
  retirement: "Retirement",
  vehicle: "Vehicle",
  debt_payoff: "Debt payoff",
  custom: "Custom",
};

export const GOAL_KIND_ICONS: Record<GoalKind, LucideIcon> = {
  emergency_fund: ShieldCheck,
  vacation: Palmtree,
  house_deposit: Home,
  education: GraduationCap,
  retirement: Landmark,
  vehicle: Car,
  debt_payoff: PiggyBank,
  custom: Target,
};

/** 1 = Critical … 5 = Someday. Lower sorts first, so ascending order is also
 * the order these should be funded in. */
export const GOAL_PRIORITY_LABELS: Record<GoalPriority, string> = {
  1: "Critical",
  2: "High",
  3: "Medium",
  4: "Low",
  5: "Someday",
};

/** Options for the goal-kind picker, in the order users most often need them. */
export const GOAL_KIND_OPTIONS: { value: GoalKind; label: string }[] = (
  [
    "emergency_fund",
    "debt_payoff",
    "house_deposit",
    "retirement",
    "education",
    "vehicle",
    "vacation",
    "custom",
  ] as GoalKind[]
).map((value) => ({ value, label: GOAL_KIND_LABELS[value] }));
