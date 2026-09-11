import { useSearchParams } from "react-router-dom";
import { INSIGHT_TABS, type InsightTab } from "../components/shell/navConfigV2";
import { useFeatures } from "../hooks/useEntitlements";
import { PageHeader, Tabs } from "../ui";
import { AnalyticsPage } from "./AnalyticsPage";
import { CoachPage } from "./CoachPage";
import { InsightsPage } from "./InsightsPage";
import { ReportsPage } from "./ReportsPage";
import { ReviewPage } from "./ReviewPage";

/**
 * The one destination that answers "what does all this mean?".
 *
 * Coach, Analytics, Reports and Insights were four rail entries answering that
 * single question, which is why users bounced between them looking for the one
 * that had the answer. The tabs are ordered by how much interpretation each
 * offers: the briefing tells you what it thinks, the review is the sit-down,
 * trends show you the shape, reports give you the raw figures, health &
 * anomalies round up the score, the milestones behind it, and the outliers
 * worth a look.
 */
export function InsightsHubPage() {
  const [params, setParams] = useSearchParams();
  const { has } = useFeatures();
  const tabs = INSIGHT_TABS.filter((t) => t.value !== "review" || has("smart_planning"));
  const requested = params.get("tab") ?? "";
  const tab = (tabs.some((t) => t.value === requested) ? requested : "coach") as InsightTab;

  const select = (next: InsightTab) => {
    setParams(next === "coach" ? {} : { tab: next }, { replace: true });
  };

  return (
    <>
      <PageHeader
        eyebrow="Meaning"
        title="Insights"
        description="What the numbers add up to — read for you, charted, tabulated, and checked for surprises."
        illustration="insight"
      />

      <Tabs label="Insight sections" value={tab} onChange={select} tabs={[...tabs]} />

      <div className="lf-tabpanel" role="tabpanel" aria-label={`${tab} panel`} tabIndex={-1}>
        {tab === "coach" && <CoachPage embedded />}
        {tab === "review" && <ReviewPage embedded />}
        {tab === "trends" && <AnalyticsPage embedded />}
        {tab === "reports" && <ReportsPage embedded />}
        {/* The old `/insights` page — anomalies and health — is now one tab of
            the destination that took its name. */}
        {tab === "anomalies" && <InsightsPage embedded />}
      </div>
    </>
  );
}
