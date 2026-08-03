import { Plus, type LucideIcon } from "lucide-react";
import { NAV_ITEMS, type NavItem } from "./navConfig";
import { NAV_ITEMS_V2 } from "./navConfigV2";

/** The destinations that earn a slot on the mobile bottom bar. Everything else
 * stays one tap away in the drawer, so parity is never lost. */
export const TAB_BAR_PATHS = ["/", "/transactions", "/budgets", "/bills", "/insights"] as const;

/**
 * Phase 5: four destinations and one verb.
 *
 * The centre slot is an action, not a place. That is the opposite of the old
 * rail's mistake — which put "Quick Add" and "Scan Receipt" in a list of
 * *places* — because a bottom bar is a toolbar, and a toolbar is exactly where
 * a verb belongs. `Accounts`, `Goals`, `Invest` and `Debt` stay one tap away in
 * the drawer.
 */
export const TAB_BAR_PATHS_V2 = ["/", "/activity", "__add__", "/plan", "/insights"] as const;

export interface TabBarSlot {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  /** Opens the add-action sheet instead of navigating. */
  action?: boolean;
}

/** Resolve tab items from the primary nav config so labels/icons/paths have a
 * single source of truth. */
export function tabBarItems(): NavItem[] {
  return TAB_BAR_PATHS.map((to) => NAV_ITEMS.find((i) => i.to === to)).filter((i): i is NavItem => !!i);
}

export function tabBarItemsV2(): TabBarSlot[] {
  return TAB_BAR_PATHS_V2.map((to): TabBarSlot | null => {
    if (to === "__add__") return { to, label: "Add", icon: Plus, action: true };
    const item = NAV_ITEMS_V2.find((i) => i.to === to);
    if (!item) return null;
    return { to: item.to, label: item.label, icon: item.icon, end: item.end };
  }).filter((i): i is TabBarSlot => !!i);
}
