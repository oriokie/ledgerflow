import type { CashflowStackLine, Position } from "../../api/projections";

export interface ScenarioHints {
  surplusMinor: number;
  rentMinor: number;
  rentLabel: string | null;
  depositMinor: number;
  debtLabel: string | null;
}

export function scenarioHints(position: Position, stack: CashflowStackLine[]): ScenarioHints {
  const surplus = Math.max(0, position.monthly_net_income_minor - position.monthly_expenses_minor);
  const rent = stack.find((line) => line.stoppable);
  const topDebt = [...position.debts].sort((a, b) => b.annual_rate - a.annual_rate)[0];
  return {
    surplusMinor: surplus,
    rentMinor: rent?.monthly_minor ?? 0,
    rentLabel: rent?.label ?? null,
    depositMinor: Math.max(0, position.liquid_minor - 3 * position.monthly_expenses_minor),
    debtLabel: topDebt?.label ?? null,
  };
}

export function decisionFieldDefaults(
  slug: string,
  hints: ScenarioHints,
  position: Position,
): Record<string, string> {
  const major = (n: number) => String(n / 100);
  const out: Record<string, string> = {};
  if (slug === "debt-or-invest" && hints.surplusMinor > 0) {
    out.monthly_amount_minor = major(hints.surplusMinor);
    out.expected_return = "7";
  }
  if (slug === "buy-or-rent") {
    if (hints.rentMinor) out.monthly_rent_minor = major(hints.rentMinor);
    if (hints.depositMinor) out.deposit_minor = major(hints.depositMinor);
  }
  if ((slug === "how-much-house" || slug === "afford-mortgage") && hints.depositMinor) {
    out.deposit_minor = major(hints.depositMinor);
  }
  if (slug === "retire") {
    out.monthly_income_needed_minor = major(position.monthly_expenses_minor);
  }
  return out;
}
