import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  useAccounts,
  useBills,
  useCashFlow,
  useCategories,
  useCategoryBreakdown,
  useNetWorth,
  useTransactions,
} from "../hooks/useFinance";
import { useBudgets, useBudgetStatus } from "../hooks/useBudgeting";
import { useGoals } from "../hooks/useGoals";
import {
  useForecast,
  useHealthScore,
  useNetWorthHistory,
  useRecommendations,
  useSpendingTrend,
} from "../hooks/useIntelligence";
import { useAuth } from "../lib/AuthContext";
import { Card, Grid, SegmentedControl, SkeletonCard } from "../ui";
import { GettingStarted } from "./dashboard/GettingStarted";
import { CashflowCalendar } from "./cashflow";
import { InsightCardCompact } from "./coach";
import { useInsights } from "../hooks/useCoach";
import { useCashflowCalendar } from "../hooks/useFinance";
import { useMembers } from "../hooks/useTenancy";
import { useDismissible } from "../hooks/useDismissible";
import { useAiEnabled } from "../hooks/useEntitlements";
import {
  BudgetProgress,
  CashFlowSummary,
  GoalsProgress,
  greeting,
  HealthCard,
  InsightsSection,
  CommittedIncomeStrip,
  NetWorthCard,
  periodRange,
  RecentActivity,
  SafeToSpend,
  SpendingByCategory,
  TrendsCard,
  UpcomingBills,
  type PeriodKey,
} from "./dashboard";

const PERIOD_OPTIONS: { value: PeriodKey; label: string }[] = [
  { value: "this-month", label: "This month" },
  { value: "last-month", label: "Last month" },
  { value: "last-30d", label: "30 days" },
  { value: "ytd", label: "Year" },
];

export function DashboardPage() {
  const { user } = useAuth();
  const [period, setPeriod] = useState<PeriodKey>("this-month");
  const range = useMemo(() => periodRange(period), [period]);
  const hello = useMemo(() => greeting(), []);

  // Core figures
  const { data: accounts, isLoading: accountsLoading } = useAccounts();
  const { data: categories } = useCategories();
  const { data: netWorth, isLoading: netWorthLoading } = useNetWorth();
  const { data: cashFlow, isLoading: cashFlowLoading } = useCashFlow(range.start, range.end);
  const { data: breakdown } = useCategoryBreakdown(range.start, range.end, "expense");

  // Trends & intelligence
  const { data: netWorthHistory } = useNetWorthHistory(6);
  const { data: spendingTrend } = useSpendingTrend(6);
  const { aiEnabled } = useAiEnabled();
  const { data: forecast } = useForecast(aiEnabled);
  const { data: health } = useHealthScore(aiEnabled);
  const { data: recommendations } = useRecommendations(aiEnabled);

  // Planning & activity
  const { data: bills } = useBills({ upcoming: 30 });
  const { data: budgets } = useBudgets();
  const firstBudget = budgets?.[0];
  const { data: budgetStatus } = useBudgetStatus(firstBudget?.id);
  const { data: goals } = useGoals();
  const { data: recentTx, isLoading: recentTxLoading } = useTransactions({ page_size: 6 });
  const { data: members } = useMembers();
  // 35 days: a full pay cycle plus a week, which is the window that answers
  // "can I make it to payday?" without becoming speculative.
  const { data: cashflowCalendar } = useCashflowCalendar({ days: 35 });
  const { data: topInsights } = useInsights();
  const [checklistDismissed, dismissChecklist] = useDismissible("onboarding-checklist");

  const primaryCurrency = netWorth?.[0]?.currency ?? accounts?.[0]?.currency ?? "USD";

  const hasAccount = (accounts?.length ?? 0) > 0;
  const hasTransaction = (recentTx?.results.length ?? 0) > 0;
  const onboarding = {
    hasAccount,
    hasTransaction,
    hasBudget: (budgets?.length ?? 0) > 0,
    hasGoal: (goals?.length ?? 0) > 0,
    hasTeammate: (members?.length ?? 0) > 1,
  };
  const setupComplete = Object.values(onboarding).every(Boolean);
  // The checklist stays until it's finished or explicitly dismissed — but once
  // there's an account and a transaction the real dashboard appears beneath it,
  // so guidance and data coexist instead of one hiding the other.
  const showChecklist = !setupComplete && !checklistDismissed;
  const dashboardReady = hasAccount && hasTransaction;
  const primaryNetWorth = netWorth?.find((n) => n.currency === primaryCurrency) ?? netWorth?.[0];
  const primaryCashFlow = cashFlow?.find((c) => c.currency === primaryCurrency) ?? cashFlow?.[0];

  const coreLoading = accountsLoading || netWorthLoading || cashFlowLoading || recentTxLoading;

  return (
    <>
      {/* Header: greeting + period control + primary action */}
      <header className="lf-dash-header">
        <div>
          <h1 className="lf-dash-greeting">
            {hello}
            {user?.first_name ? `, ${user.first_name}` : ""}
          </h1>
          <p className="lf-dash-subtitle">Here's your money at a glance · {range.label}</p>
        </div>
        {/* "Add transaction" lives once, in AppShell's persistent header —
            it's visible on every page including this one, so repeating it
            here duplicated the exact same button pointing at the exact same
            destination for no reason beyond habit. */}
        <div className="lf-dash-controls">
          <SegmentedControl<PeriodKey>
            legend="Time period"
            value={period}
            onChange={setPeriod}
            options={PERIOD_OPTIONS}
          />
        </div>
      </header>

      {coreLoading ? (
        <Grid cols={3} gap={4}>
          {[0, 1, 2].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </Grid>
      ) : (
        <>
        {/* Setup guidance leads only while there is nothing else to show. Once
            an account and a transaction exist the dashboard is the point of the
            page, and the checklist was taking the whole fold on a phone — the
            first thing a returning user saw was homework, not their balance.
            See the fold contract in docs/redesign/02-strategy-ia.md §3.3. */}
        {showChecklist && !dashboardReady && (
          <div className="lf-dash-section">
            <GettingStarted state={onboarding} onDismiss={dismissChecklist} />
          </div>
        )}
        {dashboardReady && (
        <>
          {/* Tier 1 — headline */}
          <div className="lf-dash-section">
            <Grid cols={3} gap={4}>
              <NetWorthCard netWorth={primaryNetWorth} history={netWorthHistory} currency={primaryCurrency} />
              {aiEnabled && <HealthCard health={health} />}
            </Grid>
          </div>

          {showChecklist && (
            <div className="lf-dash-section">
              <GettingStarted state={onboarding} onDismiss={dismissChecklist} compact />
            </div>
          )}

          {/* Tier 2 — this period's cash flow */}
          <div className="lf-dash-section">
            <CashFlowSummary cashFlow={primaryCashFlow} currency={primaryCurrency} />
          </div>

          {/* Tier 2a½ — the one number that answers "can I buy this?".
              Placed above the committed strip: safe-to-spend is the day's
              question, committed income is the month's. */}
          <div className="lf-dash-section">
            <SafeToSpend />
          </div>

          {/* Tier 2b — how much of the month is already spoken for.
              Renders nothing until income is recorded: "0% committed" derived
              from an absence reads as a clean bill of health, which is the
              opposite of what it means. */}
          <div className="lf-dash-section">
            <CommittedIncomeStrip />
          </div>

          {/* Tier 3 — the cash flow calendar.
              Placed above trends deliberately: "will I go negative before
              payday?" is a more urgent question than "how did last quarter
              look?", and it's the one a monthly summary can't answer. */}
          {cashflowCalendar && (
            <div className="lf-dash-section">
              <Card
                title="Cash flow calendar"
                action={
                  <Link className="lf-link" to="/cashflow">
                    Full calendar
                  </Link>
                }
              >
                <CashflowCalendar calendar={cashflowCalendar} />
              </Card>
            </div>
          )}

          {/* Tier 4 — trends (tabbed, progressive disclosure) */}
          <div className="lf-dash-section">
            <TrendsCard
              trend={spendingTrend}
              history={netWorthHistory}
              forecast={forecast}
              currency={primaryCurrency}
            />
          </div>

          {/* Tier 4 — where money goes + upcoming */}
          <div className="lf-dash-section lf-dash-split">
            <SpendingByCategory breakdown={breakdown} currency={primaryCurrency} />
            <UpcomingBills bills={bills} currency={primaryCurrency} />
          </div>

          {/* Tier 5 — planning progress */}
          <div className="lf-dash-section">
            <Grid cols={2} gap={4}>
              <BudgetProgress budget={firstBudget} status={budgetStatus} currency={primaryCurrency} />
              <GoalsProgress goals={goals} currency={primaryCurrency} />
            </Grid>
          </div>

          {/* Tier 6 — insights */}
          {/* The coach's top insights, where users already look. Capped at
              three: the dashboard is a summary, and the full ranked feed lives
              on /coach. */}
          {(topInsights?.length ?? 0) > 0 && (
            <div className="lf-dash-section">
              <Card
                title="From your coach"
                action={
                  <Link className="lf-link" to="/coach">
                    All insights
                  </Link>
                }
              >
                <div className="lf-coach-feed">
                  {(topInsights ?? []).slice(0, 3).map((insight) => (
                    <InsightCardCompact key={insight.id} insight={insight} />
                  ))}
                </div>
              </Card>
            </div>
          )}

          {aiEnabled && <InsightsSection recommendations={recommendations} />}

          {/* Tier 7 — recent activity */}
          <div className="lf-dash-section">
            <RecentActivity
              transactions={recentTx?.results}
              accounts={accounts}
              categories={categories}
              currency={primaryCurrency}
            />
          </div>
        </>
        )}
        </>
      )}
    </>
  );
}
