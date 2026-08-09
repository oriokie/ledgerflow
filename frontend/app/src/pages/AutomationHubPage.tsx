import { useSearchParams } from "react-router-dom";
import { PageHeader, Tabs } from "../ui";
import { AutomationPage } from "./AutomationPage";
import { RulesPage } from "./automation";

const TABS = [
  { value: "review", label: "Review" },
  { value: "rules", label: "Rules" },
] as const;

type AutomationTab = (typeof TABS)[number]["value"];
const VALID = new Set<string>(TABS.map((t) => t.value));

/**
 * "Review" is what LedgerFlow noticed on its own (the suggestion queue);
 * "Rules" is what the user told it to do in advance. Both answer "what is
 * automation doing with my transactions", which is why they share one nav
 * entry as tabs rather than splitting across Settings and a top-level item.
 */
export function AutomationHubPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") ?? "";
  const tab = (VALID.has(requested) ? requested : "review") as AutomationTab;

  const select = (next: AutomationTab) => {
    setParams(next === "review" ? {} : { tab: next }, { replace: true });
  };

  return (
    <>
      <PageHeader
        eyebrow="Automation"
        title="Automation"
        description="What LedgerFlow noticed on its own, and what you've told it to do automatically."
      />

      <Tabs label="Automation sections" value={tab} onChange={select} tabs={[...TABS]} />

      <div className="lf-tabpanel" role="tabpanel" aria-label={`${tab} panel`} tabIndex={-1}>
        {tab === "review" && <AutomationPage embedded />}
        {tab === "rules" && <RulesPage embedded />}
      </div>
    </>
  );
}
