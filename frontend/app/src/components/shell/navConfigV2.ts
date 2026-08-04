import {
  Banknote,
  CalendarCheck,
  LayoutDashboard,
  Lightbulb,
  ListOrdered,
  Route,
  Target,
  Users,
  TrendingDown,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export interface NavItemV2 {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  /**
   * Which live value the rail shows beside this item, if any.
   *
   * `unreviewed` was dropped in Phase 5 on the grounds that no review state
   * existed. **That was wrong** — `Transaction.needs_review` and
   * `review_reason` have been on the model all along, and the list endpoint
   * already filtered on them. What was actually missing was a *count*: the
   * ledger is cursor-paginated, so nothing could report a total. Restored in
   * Phase 6 with the endpoint that was the real gap.
   */
  metric?: "netWorth" | "unreviewed" | "dueThisWeek" | "goalProgress" | "openSuggestions";
}

export interface NavSectionV2 {
  label: string;
  items: NavItemV2[];
}

/**
 * The Phase 5 information architecture: 21 primary destinations → 8.
 *
 * Grouped by **the question the user is asking**, not by the database table
 * that answers it. The old rail had Coach, Analytics, Reports and Insights as
 * four separate destinations answering one question ("what does this mean?"),
 * and had Quick Add and Scan Receipt — two *verbs* — sitting in a list of
 * places. See `docs/redesign/02-strategy-ia.md` §2.
 */
export const NAV_SECTIONS_V2: NavSectionV2[] = [
  {
    label: "Position",
    items: [
      { to: "/", label: "Today", icon: LayoutDashboard, end: true },
      { to: "/accounts", label: "Accounts", icon: Wallet, metric: "netWorth" },
      { to: "/income", label: "Income", icon: Banknote },
      { to: "/activity", label: "Activity", icon: ListOrdered, metric: "unreviewed" },
    ],
  },
  {
    label: "Commitment",
    // Budgets, Bills, Recurring and Cash flow are four views of one fact:
    // money that is already spoken for. See §2.4.
    items: [{ to: "/plan", label: "Plan", icon: CalendarCheck, metric: "dueThisWeek" }],
  },
  {
    label: "Trajectory",
    items: [
      { to: "/goals", label: "Goals", icon: Target, metric: "goalProgress" },
      { to: "/investments", label: "Invest", icon: TrendingUp },
      { to: "/debt", label: "Debt", icon: TrendingDown },
      // The section is named Trajectory and this is the only page that draws
      // one, so it belongs here rather than under Meaning: a projection is
      // where the money is going, not what it means.
      { to: "/projections", label: "Projections", icon: Route },
    ],
  },
  {
    label: "Meaning",
    items: [
      { to: "/insights", label: "Insights", icon: Lightbulb, metric: "openSuggestions" },
      { to: "/household", label: "Household", icon: Users },
    ],
  },
];

export const NAV_ITEMS_V2: NavItemV2[] = NAV_SECTIONS_V2.flatMap((s) => s.items);

/** Tabs within `/plan`. Order is the order money becomes real: a limit you set,
 * a payment you owe, one that repeats, then all of it on a timeline. */
export const PLAN_TABS = [
  { value: "budgets", label: "Budgets" },
  { value: "bills", label: "Bills" },
  { value: "recurring", label: "Recurring" },
  { value: "cashflow", label: "Cash flow" },
] as const;

/** Tabs within `/insights`. */
export const INSIGHT_TABS = [
  { value: "coach", label: "Briefing" },
  { value: "trends", label: "Trends" },
  { value: "reports", label: "Reports" },
  { value: "anomalies", label: "Anomalies" },
] as const;

export type PlanTab = (typeof PLAN_TABS)[number]["value"];
export type InsightTab = (typeof INSIGHT_TABS)[number]["value"];

/**
 * Every path the new IA retires, and where it goes.
 *
 * A bookmark is a promise. These redirects are what make the IA change a
 * routing change rather than a data loss, and the roadmap's exit criteria name
 * them explicitly: *every retired path redirects with the right tab
 * preselected*.
 */
export const RETIRED_PATHS: Record<string, string> = {
  "/transactions": "/activity",
  "/budgets": "/plan?tab=budgets",
  "/bills": "/plan?tab=bills",
  "/recurring": "/plan?tab=recurring",
  "/cashflow": "/plan?tab=cashflow",
  "/coach": "/insights?tab=coach",
  "/analytics": "/insights?tab=trends",
  "/reports": "/insights?tab=reports",
};
