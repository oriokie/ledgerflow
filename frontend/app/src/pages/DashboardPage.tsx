import { Grid, SkeletonCard } from "../ui";
import { useDismissible } from "../hooks/useDismissible";
import { GettingStarted } from "./dashboard/GettingStarted";
import { DashGreeting } from "./dashboard/DashGreeting";
import { FinancialPulse } from "./dashboard/FinancialPulse";
import { WhatChanged } from "./dashboard/WhatChanged";
import { ActionCenter } from "./dashboard/ActionCenter";
import { CashFlowPanel } from "./dashboard/CashFlowPanel";
import { SpendingIntel } from "./dashboard/SpendingIntel";
import { BudgetPulse } from "./dashboard/BudgetPulse";
import { GoalsPulse } from "./dashboard/GoalsPulse";
import { MoneyTimeline } from "./dashboard/MoneyTimeline";
import { AccountsSnapshot } from "./dashboard/AccountsSnapshot";
import { InvestmentsSnapshot } from "./dashboard/InvestmentsSnapshot";
import { DebtSnapshot } from "./dashboard/DebtSnapshot";
import { InsightLayer } from "./dashboard/InsightLayer";
import { QuickActions } from "./dashboard/QuickActions";
import { CommittedIncomeStrip } from "./dashboard/CommittedIncomeStrip";
import { useDashboardModel } from "./dashboard/useDashboardModel";
import type { DashSectionId } from "./dashboard/personalization";
import type { ReactNode } from "react";

export function DashboardPage() {
  const model = useDashboardModel();
  const [checklistDismissed, dismissChecklist] = useDismissible("onboarding-checklist");
  const setupComplete = Object.values(model.onboarding).every(Boolean);
  const showChecklist = !setupComplete && !checklistDismissed;

  const sections: Record<DashSectionId, ReactNode> = {
    pulse: (
      <FinancialPulse
        netWorth={model.primaryNetWorth}
        history={model.netWorthHistory}
        consolidated={model.netWorthBase}
        health={model.health}
        calendar={model.cashflowCalendar}
        currency={model.primaryCurrency}
        aiEnabled={model.aiEnabled}
      />
    ),
    changed: <WhatChanged insights={model.changes} />,
    attention: <ActionCenter items={model.attention} />,
    cashflow: (
      <>
        <CashFlowPanel
          cashFlow={model.primaryCashFlow}
          trend={model.spendingTrend}
          currency={model.primaryCurrency}
          periodLabel={model.range.label}
        />
        <CommittedIncomeStrip />
      </>
    ),
    spending: (
      <SpendingIntel
        breakdown={model.breakdown}
        trend={model.spendingTrend}
        currency={model.primaryCurrency}
      />
    ),
    budget: (
      <BudgetPulse
        budget={model.firstBudget}
        status={model.budgetStatus}
        currency={model.primaryCurrency}
      />
    ),
    goals: (
      <GoalsPulse
        goals={model.goals}
        forecasts={model.goalForecasts}
        currency={model.primaryCurrency}
      />
    ),
    timeline: (
      <MoneyTimeline
        calendar={model.cashflowCalendar}
        bills={model.bills}
        currency={model.primaryCurrency}
      />
    ),
    accounts: (
      <AccountsSnapshot accounts={model.accounts} currency={model.primaryCurrency} />
    ),
    investments: <InvestmentsSnapshot portfolio={model.portfolio} />,
    debt: <DebtSnapshot summary={model.debtSummary} debts={model.debts} />,
    insights: (
      <InsightLayer
        insights={model.topInsights}
        recommendations={model.recommendations}
        aiEnabled={model.aiEnabled}
      />
    ),
    actions: <QuickActions />,
  };

  const MAIN: DashSectionId[] = ["pulse", "changed", "cashflow", "spending", "insights", "actions"];
  const RAIL: DashSectionId[] = [
    "attention",
    "timeline",
    "goals",
    "budget",
    "accounts",
    "investments",
    "debt",
  ];

  const available = new Set(model.sectionOrder);
  // Always keep structural main/rail sections that personalization may reorder
  // but not drop (attention, accounts, etc.). Optional surfaces stay gated.
  for (const id of MAIN) {
    if (id === "insights") continue;
    available.add(id);
  }
  for (const id of ["attention", "timeline", "goals", "budget", "accounts"] as DashSectionId[]) {
    available.add(id);
  }

  const orderedMain = model.sectionOrder
    .filter((id) => MAIN.includes(id) && available.has(id))
    .concat(MAIN.filter((id) => available.has(id) && !model.sectionOrder.includes(id)));
  const orderedRail = model.sectionOrder
    .filter((id) => RAIL.includes(id) && available.has(id))
    .concat(RAIL.filter((id) => available.has(id) && !model.sectionOrder.includes(id)));

  return (
    <div className="lf-cmd">
      <DashGreeting
        hello={model.hello}
        firstName={model.user?.first_name}
        statement={model.statement}
        period={model.period}
        onPeriodChange={model.setPeriod}
        rangeLabel={model.range.label}
      />

      {model.coreLoading ? (
        <Grid cols={3} gap={4}>
          {[0, 1, 2].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </Grid>
      ) : (
        <>
          {showChecklist && !model.dashboardReady && (
            <div className="lf-cmd-onboard">
              <GettingStarted state={model.onboarding} onDismiss={dismissChecklist} />
            </div>
          )}

          {model.dashboardReady && (
            <>
              {showChecklist && (
                <div className="lf-cmd-onboard lf-cmd-onboard--compact">
                  <GettingStarted
                    state={model.onboarding}
                    onDismiss={dismissChecklist}
                    compact
                  />
                </div>
              )}

              <div className="lf-cmd-layout">
                <div className="lf-cmd-main">
                  {orderedMain.map((id) => (
                    <div key={id} className="lf-cmd-slot" data-section={id}>
                      {sections[id]}
                    </div>
                  ))}
                </div>
                <aside className="lf-cmd-rail" aria-label="Priorities and planning">
                  {orderedRail.map((id) => {
                    const node = sections[id];
                    if (node == null) return null;
                    return (
                      <div key={id} className="lf-cmd-slot" data-section={id}>
                        {node}
                      </div>
                    );
                  })}
                </aside>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
