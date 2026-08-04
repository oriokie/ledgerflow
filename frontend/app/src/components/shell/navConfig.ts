import {
  Banknote,
  Camera,
  CalendarDays,
  ArrowLeftRight,
  BarChart3,
  CreditCard,
  FolderTree,
  LayoutDashboard,
  Lightbulb,
  PieChart,
  PiggyBank,
  Receipt,
  RefreshCw,
  Route,
  Settings,
  Bot,
  Sparkles,
  Zap,
  Target,
  TrendingDown,
  TrendingUp,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

/** Single source of truth for primary navigation — consumed by the desktop
 * rail, the mobile drawer, and the ⌘K command palette. */
/** The one nav entry behind a per-user preference (UserProfile.show_receipt_scanner).
 *  Exported so the sidebar filters on an identifier rather than a string it
 *  could drift from. */
export const RECEIPT_SCAN_PATH = "/receipts/scan";

export const NAV_SECTIONS: NavSection[] = [
  {
    label: "Money",
    items: [
      { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
      { to: "/transactions", label: "Transactions", icon: ArrowLeftRight },
      { to: "/accounts", label: "Accounts", icon: Wallet },
      { to: "/income", label: "Income", icon: Banknote },
      { to: "/categories", label: "Categories", icon: FolderTree },
      { to: "/bills", label: "Bills", icon: Receipt },
      { to: "/recurring", label: "Recurring", icon: RefreshCw },
    ],
  },
  {
    label: "Planning",
    items: [
      { to: "/budgets", label: "Budgets", icon: PiggyBank },
      { to: "/goals", label: "Goals", icon: Target },
      { to: "/investments", label: "Investments", icon: TrendingUp },
      { to: "/debt", label: "Debt", icon: TrendingDown },
      { to: "/projections", label: "Projections", icon: Route },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { to: "/coach", label: "Coach", icon: Bot },
      { to: "/cashflow", label: "Cash flow", icon: CalendarDays },
      { to: "/analytics", label: "Analytics", icon: BarChart3 },
      { to: "/reports", label: "Reports", icon: PieChart },
      { to: "/insights", label: "Insights", icon: Lightbulb },
      { to: "/automation", label: "Automation", icon: Sparkles },
      { to: "/quick-add", label: "Quick Add", icon: Zap },
      { to: RECEIPT_SCAN_PATH, label: "Scan Receipt", icon: Camera },
    ],
  },
  {
    label: "Workspace",
    items: [
      { to: "/household", label: "Household", icon: Users },
      { to: "/members", label: "Members", icon: Users },
      { to: "/billing", label: "Billing", icon: CreditCard },
      { to: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

/** Flattened list for search/command-palette use. */
export const NAV_ITEMS: NavItem[] = NAV_SECTIONS.flatMap((s) => s.items);
