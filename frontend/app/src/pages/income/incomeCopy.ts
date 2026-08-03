import type {
  DeductionKind,
  IncomeFrequency,
  IncomeKind,
  Reliability,
} from "../../api/income";

/**
 * Labels for the income enums.
 *
 * Kept out of the components because the same words appear in the list, the
 * form and the detail panel, and three copies drift — always toward the one
 * nobody reads.
 */

export const KIND_LABEL: Record<IncomeKind, string> = {
  employment: "Employment",
  self_employment: "Self-employment",
  business: "Business",
  rental: "Rental",
  pension: "Pension",
  benefits: "Benefits or grant",
  investment: "Investment income",
  other: "Other",
};

export const FREQUENCY_LABEL: Record<IncomeFrequency, string> = {
  daily: "Daily",
  weekly: "Weekly",
  fortnightly: "Every two weeks",
  semi_monthly: "Twice a month",
  monthly: "Monthly",
  quarterly: "Quarterly",
  annual: "Annually",
  ad_hoc: "Whenever it comes",
};

export const RELIABILITY_LABEL: Record<Reliability, string> = {
  fixed: "Fixed",
  variable: "Varies",
  irregular: "Irregular",
};

/** What each reliability actually promises, in the user's terms. */
export const RELIABILITY_HELP: Record<Reliability, string> = {
  fixed: "Same amount, same day. Projected at face value.",
  variable: "Arrives reliably, amount moves. Projected from what you've actually received.",
  irregular: "Neither amount nor date is promised. Shown as an estimate, never as a fact.",
};

export const DEDUCTION_LABEL: Record<DeductionKind, string> = {
  tax: "Income tax",
  social_security: "Social security",
  pension: "Pension",
  health: "Health insurance",
  loan: "Loan repayment",
  union: "Union or association",
  other: "Other",
};

/** Cadences that land on a numbered day of the month. */
export const DAY_OF_MONTH_CADENCES: IncomeFrequency[] = [
  "semi_monthly",
  "monthly",
  "quarterly",
  "annual",
];

/**
 * How to describe a committed-income ratio.
 *
 * The bands are stated here rather than inline so the wording and the
 * thresholds cannot drift apart, and so the thresholds are reviewable as a
 * claim rather than buried in a ternary. They are rules of thumb and the copy
 * says so — this product does not tell people what their finances mean, it
 * tells them what the number is and what it is made of.
 */
export function committedBand(pct: number): { tone: "positive" | "warning" | "critical"; note: string } {
  if (pct < 50) {
    return { tone: "positive", note: "Most of your income is still yours to direct." };
  }
  if (pct < 70) {
    return { tone: "warning", note: "Over half is spoken for before you choose anything." };
  }
  return {
    tone: "critical",
    note: "Very little is left to absorb a surprise or to save with.",
  };
}
