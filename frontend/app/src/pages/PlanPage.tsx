import { useSearchParams } from "react-router-dom";
import { PLAN_TABS, type PlanTab } from "../components/shell/navConfigV2";
import { PageHeader, Tabs } from "../ui";
import { BillsPage } from "./BillsPage";
import { BudgetsPage } from "./BudgetsPage";
import { CashflowPage } from "./CashflowPage";
import { RecurringPage } from "./RecurringPage";

const VALID = new Set<string>(PLAN_TABS.map((t) => t.value));

/**
 * Everything already spoken for, in one place.
 *
 * Budgets, Bills, Recurring and Cash flow were four destinations describing one
 * fact: money that is no longer yours to allocate. A budget is a limit you set,
 * a bill is a payment you owe, a recurrence is a bill that repeats, and the
 * cash-flow calendar is all of them laid on a timeline. Splitting them made the
 * user reconcile four screens mentally; joined, the forecast is visibly
 * *derived from* the bills and recurrences one tab away — which is also what
 * makes an empty calendar self-explaining rather than mysterious.
 *
 * The tab lives in the query string, not in component state, so
 * `/plan?tab=bills` is linkable, bookmarkable, and is where `/bills` redirects
 * to. See `docs/redesign/02-strategy-ia.md` §2.4.
 */
export function PlanPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") ?? "";
  const tab = (VALID.has(requested) ? requested : "budgets") as PlanTab;

  const select = (next: PlanTab) => {
    // `replace` so tabbing doesn't fill the back stack — pressing Back should
    // leave Plan, not walk backwards through the tabs you looked at.
    setParams(next === "budgets" ? {} : { tab: next }, { replace: true });
  };

  return (
    <>
      <PageHeader
        eyebrow="Commitment"
        title="Plan"
        description="What's already spoken for — limits you've set, payments you owe, and where that leaves you."
      />

      <Tabs label="Plan sections" value={tab} onChange={select} tabs={[...PLAN_TABS]} />

      <div className="lf-tabpanel" role="tabpanel" aria-label={`${tab} panel`} tabIndex={-1}>
        {tab === "budgets" && <BudgetsPage embedded />}
        {tab === "bills" && <BillsPage embedded />}
        {tab === "recurring" && <RecurringPage embedded />}
        {tab === "cashflow" && <CashflowPage embedded />}
      </div>
    </>
  );
}
