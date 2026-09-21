import type { PolicyKind, PremiumFrequency } from "../../api/insurance";

export const POLICY_KIND_OPTIONS: { value: PolicyKind; label: string }[] = [
  { value: "home", label: "Home" },
  { value: "motor", label: "Motor" },
  { value: "life", label: "Life" },
  { value: "health", label: "Health" },
  { value: "liability", label: "Liability" },
  { value: "other", label: "Something else" },
];

export const POLICY_KIND_LABELS: Record<PolicyKind, string> = Object.fromEntries(
  POLICY_KIND_OPTIONS.map((o) => [o.value, o.label]),
) as Record<PolicyKind, string>;

export const PREMIUM_FREQUENCY_OPTIONS: { value: PremiumFrequency; label: string }[] = [
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "annual", label: "Annually" },
];
