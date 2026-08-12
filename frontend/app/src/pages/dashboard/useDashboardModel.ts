import { useMemo, useState } from "react";
import {
  useAccounts,
  useBills,
  useCashFlow,
  useCashflowCalendar,
  useCategories,
  useCategoryBreakdown,
  useNetWorth,
  useNetWorthBase,
  useReviewCount,
  useTransactions,
} from "../../hooks/useFinance";
import { useBudgets, useBudgetStatus } from "../../hooks/useBudgeting";
import { useGoalForecasts, useGoals } from "../../hooks/useGoals";
import {
  useForecast,
  useHealthScore,
  useNetWorthHistory,
  useRecommendations,
  useSpendingTrend,
} from "../../hooks/useIntelligence";
import { useInsights } from "../../hooks/useCoach";
import { useDebtSummary, useDebts } from "../../hooks/useDebt";
import { usePortfolio } from "../../hooks/useInvestments";
import { useMembers } from "../../hooks/useTenancy";
import { useAiEnabled } from "../../hooks/useEntitlements";
import { useAuth } from "../../lib/AuthContext";
import { useIncomeSummary } from "../../hooks/useIncome";
import {
  adaptiveSectionPriority,
  buildAttentionItems,
  buildChangeInsights,
  contextualStatement,
} from "./personalization";
import { greeting, periodRange, type PeriodKey } from "./metrics";

export function useDashboardModel() {
  const { user, activeWorkspace } = useAuth();
  const [period, setPeriod] = useState<PeriodKey>("this-month");
  const range = useMemo(() => periodRange(period), [period]);
  const hello = useMemo(() => greeting(), []);

  const { data: accounts, isLoading: accountsLoading } = useAccounts();
  const { data: categories } = useCategories();
  const { data: netWorth, isLoading: netWorthLoading } = useNetWorth();
  const { data: netWorthBase } = useNetWorthBase();
  const { data: cashFlow, isLoading: cashFlowLoading } = useCashFlow(range.start, range.end);
  const { data: breakdown } = useCategoryBreakdown(range.start, range.end, "expense");
  const { data: netWorthHistory } = useNetWorthHistory(6);
  const { data: spendingTrend } = useSpendingTrend(6);
  const { aiEnabled } = useAiEnabled();
  const { data: forecast } = useForecast(aiEnabled);
  const { data: health } = useHealthScore(aiEnabled);
  const { data: recommendations } = useRecommendations(aiEnabled);
  const { data: bills } = useBills({ upcoming: 30 });
  const { data: budgets } = useBudgets();
  const firstBudget = budgets?.[0];
  const { data: budgetStatus } = useBudgetStatus(firstBudget?.id);
  const { data: goals } = useGoals();
  const { data: goalForecasts } = useGoalForecasts();
  const { data: recentTx, isLoading: recentTxLoading } = useTransactions({ page_size: 8 });
  const { data: members } = useMembers();
  const { data: cashflowCalendarRaw } = useCashflowCalendar({ days: 35 });
  const cashflowCalendar = cashflowCalendarRaw ?? undefined;
  const { data: topInsights } = useInsights();
  const { data: reviewCount } = useReviewCount();
  const { data: portfolioRaw } = usePortfolio();
  const portfolio = portfolioRaw ?? undefined;
  const { data: debts } = useDebts();
  const { data: debtSummaryRaw } = useDebtSummary();
  const debtSummary = debtSummaryRaw ?? undefined;
  const { data: incomeSummary } = useIncomeSummary();

  const primaryCurrency =
    netWorth?.[0]?.currency ??
    accounts?.[0]?.currency ??
    activeWorkspace?.tenant.base_currency ??
    "KES";
  const primaryNetWorth = netWorth?.find((n) => n.currency === primaryCurrency) ?? netWorth?.[0];
  const primaryCashFlow = cashFlow?.find((c) => c.currency === primaryCurrency) ?? cashFlow?.[0];

  const hasAccount = (accounts?.length ?? 0) > 0;
  const hasTransaction = (recentTx?.results.length ?? 0) > 0;
  const onboarding = {
    hasCurrency: !!activeWorkspace?.tenant.base_currency_chosen_at,
    hasAccount,
    hasTransaction,
    hasBudget: (budgets?.length ?? 0) > 0,
    hasGoal: (goals?.length ?? 0) > 0,
    hasTeammate: (members?.length ?? 0) > 1,
  };
  const dashboardReady = hasAccount && hasTransaction;

  const overdueBills = (bills ?? []).filter((b) => b.status === "overdue").length;
  const statement = useMemo(
    () =>
      contextualStatement({
        firstName: user?.first_name,
        netWorth: primaryNetWorth,
        history: netWorthHistory,
        cashFlow: primaryCashFlow,
        health,
        calendar: cashflowCalendar,
        overdueBills,
        currency: primaryCurrency,
      }),
    [
      user?.first_name,
      primaryNetWorth,
      netWorthHistory,
      primaryCashFlow,
      health,
      cashflowCalendar,
      overdueBills,
      primaryCurrency,
    ],
  );

  const changes = useMemo(
    () =>
      buildChangeInsights({
        spendingTrend,
        history: netWorthHistory,
        calendar: cashflowCalendar,
        cashFlow: primaryCashFlow,
        currency: primaryCurrency,
      }),
    [spendingTrend, netWorthHistory, cashflowCalendar, primaryCashFlow, primaryCurrency],
  );

  const attention = useMemo(
    () =>
      buildAttentionItems({
        bills,
        budgetStatus,
        calendar: cashflowCalendar,
        goals,
        reviewCount: reviewCount?.count,
        debtAlerts: debtSummary?.alerts,
        insights: topInsights,
        recommendations,
        currency: primaryCurrency,
      }),
    [
      bills,
      budgetStatus,
      cashflowCalendar,
      goals,
      reviewCount,
      debtSummary,
      topInsights,
      recommendations,
      primaryCurrency,
    ],
  );

  const hasBudgetExceptions = (budgetStatus?.lines ?? []).some(
    (l) => l.over_budget || l.percent_used >= 90,
  );
  const hasInvestments = (portfolio?.holding_count ?? 0) > 0;
  const hasDebt = (debtSummary?.debt_count ?? debts?.length ?? 0) > 0;
  const hasInsights = (topInsights?.length ?? 0) > 0 || (recommendations?.length ?? 0) > 0;

  const sectionOrder = useMemo(
    () =>
      adaptiveSectionPriority({
        hasAttention: attention.length > 0,
        hasCashRisk: !!cashflowCalendar?.first_negative_on,
        hasGoals: (goals ?? []).some((g) => g.status === "active"),
        hasBudgetExceptions,
        hasInvestments,
        hasDebt,
        hasInsights,
      }),
    [
      attention.length,
      cashflowCalendar?.first_negative_on,
      goals,
      hasBudgetExceptions,
      hasInvestments,
      hasDebt,
      hasInsights,
    ],
  );

  const coreLoading = accountsLoading || netWorthLoading || cashFlowLoading || recentTxLoading;

  return {
    user,
    activeWorkspace,
    period,
    setPeriod,
    range,
    hello,
    statement,
    accounts,
    categories,
    primaryCurrency,
    primaryNetWorth,
    primaryCashFlow,
    netWorthBase,
    netWorthHistory,
    spendingTrend,
    forecast,
    health,
    recommendations,
    bills,
    firstBudget,
    budgetStatus,
    goals,
    goalForecasts,
    recentTx,
    cashflowCalendar,
    topInsights,
    portfolio,
    debts,
    debtSummary,
    incomeSummary,
    breakdown,
    aiEnabled,
    onboarding,
    dashboardReady,
    changes,
    attention,
    sectionOrder,
    hasInvestments,
    hasDebt,
    coreLoading,
  };
}

export type DashboardModel = ReturnType<typeof useDashboardModel>;
