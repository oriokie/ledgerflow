import {
  Building2,
  Cpu,
  ShieldCheck,
  SlidersHorizontal,
  Tags,
  User,
  type LucideIcon,
} from "lucide-react";

export interface SettingsNavItem {
  /** Path segment under /settings. */
  slug: string;
  label: string;
  icon: LucideIcon;
}

export interface SettingsNavGroup {
  label: string;
  items: SettingsNavItem[];
}

/**
 * Single source of truth for the settings sub-navigation.
 *
 * The redesign spec called for flattening these two groups into one list, on
 * the grounds that six leaf items don't need two levels. Kept grouped, because
 * the grouping is not hierarchy for its own sake — it separates *what changes
 * for you* from *what changes for everyone in this workspace*, which in a
 * multi-tenant product is the most consequential thing about a setting.
 * Renaming your own display name and renaming the workspace read alike in a
 * flat list, and they are not alike.
 *
 * The labels now say that outright rather than leaving it implied by two nouns.
 * Flattening would save two lines of nav and cost the only signal on the page
 * about blast radius.
 */
export const SETTINGS_NAV: SettingsNavGroup[] = [
  {
    label: "Your account",
    items: [
      { slug: "profile", label: "Profile", icon: User },
      { slug: "security", label: "Security", icon: ShieldCheck },
      { slug: "preferences", label: "Preferences", icon: SlidersHorizontal },
    ],
  },
  {
    label: "Whole workspace",
    items: [
      { slug: "workspace", label: "General", icon: Building2 },
      { slug: "taxonomy", label: "Categories & tags", icon: Tags },
      { slug: "intelligence", label: "AI & insights", icon: Cpu },
    ],
  },
];

/** Flat list of valid slugs — handy for redirects and tests. */
export const SETTINGS_SLUGS: string[] = SETTINGS_NAV.flatMap((g) => g.items.map((i) => i.slug));
