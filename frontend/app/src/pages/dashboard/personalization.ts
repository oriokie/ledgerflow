import type {
  Bill,
  BudgetStatus,
  CashFlowByCurrency,
  CashflowCalendar,
  HealthScore,
  Insight,
  NetWorthByCurrency,
  NetWorthHistoryPoint,
  Recommendation,
  RecurringTransaction,
  SavingsGoal,
  SpendingTrendPoint,
} from "../../api/types";
import type { IncomeSource } from "../../api/income";
import { formatAmount } from "../../lib/money";
import { percentChange, savingsRate } from "./metrics";

export type AttentionKind =
  | "overdue_bill"
  | "bill_soon"
  | "missed_income"
  | "recurring_due"
  | "budget_over"
  | "cashflow_risk"
  | "goal_off_track"
  | "review"
  | "debt_alert"
  | "coach"
  | "recommendation";

export interface AttentionItem {
  id: string;
  kind: AttentionKind;
  urgency: number;
  title: string;
  body: string;
  href: string;
  cta: string;
}

export type DashSectionId =
  | "pulse"
  | "changed"
  | "attention"
  | "cashflow"
  | "spending"
  | "budget"
  | "goals"
  | "timeline"
  | "accounts"
  | "investments"
  | "debt"
  | "insights"
  | "actions";

export interface ChangeInsight {
  id: string;
  title: string;
  body: string;
  tone: "good" | "warn" | "neutral";
}

/**
 * One sentence that situates the user — drawn only from figures we actually have.
 * Returns null when there isn't enough signal to say anything honest.
 */
export function contextualStatement(input: {
  firstName?: string;
  netWorth?: NetWorthByCurrency;
  history?: NetWorthHistoryPoint[];
  cashFlow?: CashFlowByCurrency;
  health?: HealthScore;
  calendar?: CashflowCalendar;
  overdueBills: number;
  currency: string;
}): string | null {
  const { netWorth, history, cashFlow, health, calendar, overdueBills, currency } = input;

  if (overdueBills > 0) {
    return overdueBills === 1
      ? "One bill is overdue — clearing it protects the rest of the month."
      : `${overdueBills} bills are overdue — start with the oldest.`;
  }

  if (calendar?.first_negative_on) {
    const when = new Date(calendar.first_negative_on).toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
    });
    return `Cash is projected to run short around ${when}. The calendar shows what drives it.`;
  }

  if (health?.score != null) {
    if (health.score >= 70) {
      return `Your financial health looks ${health.band.toLowerCase()} — keep the habits that got you here.`;
    }
    if (health.score < 45) {
      return `Health is in the ${health.band.toLowerCase()} band. The action list below is ordered by impact.`;
    }
  }

  const points = history ?? [];
  if (netWorth && points.length >= 2) {
    const delta = percentChange(
      points[points.length - 1].net_minor,
      points[0].net_minor,
    );
    if (delta != null && Math.abs(delta) >= 1) {
      const dir = delta > 0 ? "up" : "down";
      return `Net worth is ${dir} ${Math.abs(delta).toFixed(1)}% over six months — now ${formatAmount(netWorth.net_minor, currency)}.`;
    }
  }

  if (cashFlow) {
    const rate = savingsRate(cashFlow.income_minor, cashFlow.expense_minor);
    if (rate != null) {
      if (rate < 0) {
        return `Spending outpaced income this period by ${formatAmount(Math.abs(cashFlow.net_minor), currency)}.`;
      }
      return `You're keeping about ${Math.round(rate)}% of income this period.`;
    }
    if (cashFlow.expense_minor > 0 && cashFlow.income_minor === 0) {
      return `Spending of ${formatAmount(cashFlow.expense_minor, currency)} with no income recorded yet this period.`;
    }
  }

  if (netWorth) {
    return `Net worth stands at ${formatAmount(netWorth.net_minor, currency)}.`;
  }

  return null;
}

/** Derive “what changed” from trends and calendar — never invents figures. */
export function buildChangeInsights(input: {
  spendingTrend?: SpendingTrendPoint[];
  history?: NetWorthHistoryPoint[];
  calendar?: CashflowCalendar;
  cashFlow?: CashFlowByCurrency;
  currency: string;
}): ChangeInsight[] {
  const out: ChangeInsight[] = [];
  const trend = input.spendingTrend ?? [];

  if (trend.length >= 2) {
    const prev = trend[trend.length - 2];
    const curr = trend[trend.length - 1];
    const spendDelta = percentChange(curr.expense_minor, prev.expense_minor);
    if (spendDelta != null && Math.abs(spendDelta) >= 3) {
      out.push({
        id: "spend-mom",
        title: spendDelta > 0 ? "Spending rose" : "Spending eased",
        body: `${Math.abs(spendDelta).toFixed(0)}% vs the prior month (${formatAmount(curr.expense_minor, input.currency)} this month).`,
        tone: spendDelta > 8 ? "warn" : spendDelta < 0 ? "good" : "neutral",
      });
    }
    const incomeDelta = percentChange(curr.income_minor, prev.income_minor);
    if (incomeDelta != null && Math.abs(incomeDelta) >= 5 && curr.income_minor > 0) {
      out.push({
        id: "income-mom",
        title: incomeDelta > 0 ? "Income up" : "Income down",
        body: `${Math.abs(incomeDelta).toFixed(0)}% vs the prior month.`,
        tone: incomeDelta > 0 ? "good" : "warn",
      });
    }
  }

  const hist = input.history ?? [];
  if (hist.length >= 2) {
    const last = hist[hist.length - 1];
    const prior = hist[hist.length - 2];
    const d = last.net_minor - prior.net_minor;
    if (d !== 0) {
      out.push({
        id: "nw-step",
        title: d > 0 ? "Net worth edged up" : "Net worth edged down",
        body: `${formatAmount(Math.abs(d), input.currency)} since last snapshot.`,
        tone: d > 0 ? "good" : "warn",
      });
    }
  }

  if (input.calendar) {
    const cal = input.calendar;
    if (cal.negative_day_count > 0) {
      out.push({
        id: "cf-neg",
        title: "Projected shortfall days",
        body: `${cal.negative_day_count} day${cal.negative_day_count === 1 ? "" : "s"} in the next window close below zero.`,
        tone: "warn",
      });
    } else if (cal.safe_to_spend_minor > 0) {
      out.push({
        id: "sts",
        title: "Room to spend safely",
        body: `${formatAmount(cal.safe_to_spend_minor, cal.currency)} beyond scheduled bills${
          cal.safe_to_spend_basis === "everyday" ? " and usual habits" : ""
        }.`,
        tone: "good",
      });
    }
  }

  return out.slice(0, 4);
}

export function buildAttentionItems(input: {
  bills?: Bill[];
  budgetStatus?: BudgetStatus;
  budgetCurrency?: string;
  calendar?: CashflowCalendar;
  goals?: SavingsGoal[];
  reviewCount?: number;
  debtAlerts?: { severity: string; title: string; body: string; account_id: string | null }[];
  insights?: Insight[];
  recommendations?: Recommendation[];
  incomeSources?: IncomeSource[];
  recurring?: RecurringTransaction[];
  currency: string;
}): AttentionItem[] {
  const items: AttentionItem[] = [];
  const currency = input.currency;
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  for (const b of input.bills ?? []) {
    if (b.status === "overdue") {
      items.push({
        id: `bill-od-${b.id}`,
        kind: "overdue_bill",
        urgency: 100,
        title: `${b.name} is overdue`,
        body: formatAmount(b.amount_minor, b.currency || currency),
        href: "/plan?tab=bills",
        cta: "Pay bill",
      });
    } else if (b.status === "upcoming") {
      const days =
        typeof b.days_until_due === "number"
          ? b.days_until_due
          : Math.ceil((new Date(b.due_on).getTime() - Date.now()) / 86_400_000);
      if (days <= 3) {
        items.push({
          id: `bill-soon-${b.id}`,
          kind: "bill_soon",
          urgency: 80 - days,
          title: days <= 0 ? `${b.name} due today` : `${b.name} due in ${days}d`,
          body: formatAmount(b.amount_minor, b.currency || currency),
          href: "/plan?tab=bills",
          cta: "View bills",
        });
      }
    }
  }

  for (const source of input.incomeSources ?? []) {
    if (!source.overdue_expected_on || !source.is_current) continue;
    const due = new Date(source.overdue_expected_on + "T00:00:00");
    const daysLate = Math.max(0, Math.round((today.getTime() - due.getTime()) / 86_400_000));
    const when =
      daysLate === 0
        ? "due today"
        : daysLate === 1
          ? "was due yesterday"
          : `was due ${daysLate} days ago`;
    items.push({
      id: `income-miss-${source.id}`,
      kind: "missed_income",
      urgency: 88 + Math.min(10, daysLate),
      title: `${source.name} ${when}`,
      body: `Expected ${formatAmount(source.expected_net_minor, source.currency)} — record it if it arrived.`,
      href: "/income",
      cta: "Record income",
    });
  }

  for (const rec of input.recurring ?? []) {
    if (!rec.is_active) continue;
    const due = new Date(rec.next_run_on + "T00:00:00");
    const days = Math.round((due.getTime() - today.getTime()) / 86_400_000);
    if (days > 2) continue;
    const isIncome = rec.txn_type === "income";
    const label = rec.memo?.trim() || (isIncome ? "Recurring income" : "Recurring payment");
    items.push({
      id: `rec-due-${rec.id}`,
      kind: "recurring_due",
      urgency: days < 0 ? 92 : 78 - days,
      title:
        days < 0
          ? `${label} overdue`
          : days === 0
            ? `${label} due today`
            : `${label} due in ${days}d`,
      body: formatAmount(rec.amount_minor, rec.currency || currency),
      href: "/plan?tab=recurring",
      cta: isIncome ? "Mark received" : "Mark paid",
    });
  }

  for (const line of input.budgetStatus?.lines ?? []) {
    if (line.over_budget) {
      items.push({
        id: `budget-${line.line_id}`,
        kind: "budget_over",
        urgency: 70 + Math.min(20, line.percent_used - 100),
        title: `${line.category_name} over budget`,
        body: `${Math.round(line.percent_used)}% used`,
        href: "/plan?tab=budgets",
        cta: "Review budget",
      });
    } else if (line.percent_used >= 90) {
      items.push({
        id: `budget-warn-${line.line_id}`,
        kind: "budget_over",
        urgency: 55,
        title: `${line.category_name} nearly spent`,
        body: `${Math.round(line.percent_used)}% of the limit`,
        href: "/plan?tab=budgets",
        cta: "Check budget",
      });
    }
  }

  if (input.calendar?.first_negative_on) {
    items.push({
      id: "cashflow-risk",
      kind: "cashflow_risk",
      urgency: 90,
      title: "Cash may run short",
      body: `First shortfall projected ${new Date(input.calendar.first_negative_on).toLocaleDateString(undefined, {
        day: "numeric",
        month: "short",
      })}`,
      href: "/plan?tab=cashflow",
      cta: "Open calendar",
    });
  }

  for (const g of input.goals ?? []) {
    if (g.status !== "active") continue;
    if (g.required_monthly_minor != null && g.planned_monthly_minor != null) {
      if (g.planned_monthly_minor < g.required_monthly_minor && !g.is_met) {
        items.push({
          id: `goal-${g.id}`,
          kind: "goal_off_track",
          urgency: 50,
          title: `${g.name} needs a higher pace`,
          body: "Planned contributions fall short of the target date.",
          href: "/goals",
          cta: "Adjust goal",
        });
      }
    }
  }

  if ((input.reviewCount ?? 0) > 0) {
    items.push({
      id: "review",
      kind: "review",
      urgency: 45,
      title: `${input.reviewCount} transaction${input.reviewCount === 1 ? "" : "s"} to review`,
      body: "Uncategorized or flagged activity waiting on you.",
      href: "/review",
      cta: "Review",
    });
  }

  for (const alert of input.debtAlerts ?? []) {
    const sev = alert.severity === "critical" ? 95 : alert.severity === "warning" ? 65 : 40;
    items.push({
      id: `debt-${alert.title}`,
      kind: "debt_alert",
      urgency: sev,
      title: alert.title,
      body: alert.body,
      href: "/debt",
      cta: "Open debt",
    });
  }

  for (const insight of (input.insights ?? []).slice(0, 3)) {
    if (insight.severity === "info" && items.length >= 4) continue;
    const sev =
      insight.severity === "critical" ? 85 : insight.severity === "warning" ? 60 : insight.severity === "opportunity" ? 35 : 25;
    items.push({
      id: `insight-${insight.id}`,
      kind: "coach",
      urgency: sev,
      title: insight.title,
      body: insight.body,
      href: "/insights?tab=coach",
      cta: "See insight",
    });
  }

  for (const rec of (input.recommendations ?? []).slice(0, 2)) {
    items.push({
      id: `rec-${rec.kind}-${rec.title}`,
      kind: "recommendation",
      urgency: rec.severity === "critical" ? 75 : rec.severity === "warning" ? 48 : 30,
      title: rec.title,
      body: rec.body,
      href: "/insights",
      cta: "Learn more",
    });
  }

  return items.sort((a, b) => b.urgency - a.urgency).slice(0, 8);
}

/**
 * Adaptive section order for the main column / rail.
 * Mobile CSS remaps visually; this drives desktop primary narrative.
 */
export function adaptiveSectionPriority(input: {
  hasAttention: boolean;
  hasCashRisk: boolean;
  hasGoals: boolean;
  hasBudgetExceptions: boolean;
  hasInvestments: boolean;
  hasDebt: boolean;
  hasInsights: boolean;
}): DashSectionId[] {
  const base: DashSectionId[] = [
    "pulse",
    "attention",
    "changed",
    "cashflow",
    "timeline",
    "goals",
    "budget",
    "spending",
    "accounts",
    "investments",
    "debt",
    "insights",
    "actions",
  ];

  let ordered: DashSectionId[];
  if (input.hasCashRisk) {
    ordered = prioritize(base, ["pulse", "attention", "timeline", "cashflow", "changed"]);
  } else if (input.hasAttention) {
    ordered = prioritize(base, ["pulse", "attention", "changed", "cashflow"]);
  } else if (input.hasBudgetExceptions) {
    ordered = prioritize(base, ["pulse", "attention", "budget", "spending", "cashflow"]);
  } else if (input.hasGoals && !input.hasInvestments) {
    ordered = prioritize(base, ["pulse", "changed", "goals", "cashflow", "attention"]);
  } else {
    ordered = base;
  }

  return ordered.filter((id) => {
    if (id === "investments" && !input.hasInvestments) return false;
    if (id === "debt" && !input.hasDebt) return false;
    if (id === "insights" && !input.hasInsights) return false;
    return true;
  });
}

function prioritize(base: DashSectionId[], head: DashSectionId[]): DashSectionId[] {
  const seen = new Set<DashSectionId>();
  const out: DashSectionId[] = [];
  for (const id of head) {
    if (!seen.has(id) && base.includes(id)) {
      out.push(id);
      seen.add(id);
    }
  }
  for (const id of base) {
    if (!seen.has(id)) {
      out.push(id);
      seen.add(id);
    }
  }
  return out;
}
