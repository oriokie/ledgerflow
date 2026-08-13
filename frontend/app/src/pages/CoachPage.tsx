import { RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";
import type { BriefingPeriod } from "../api/types";
import { useBriefing, useDecideInsight, useGenerateInsights, useInsights } from "../hooks/useCoach";
import { useAuth } from "../lib/AuthContext";
import { Banner, Button, Card, EmptyState, PageHeader, SegmentedControl, SkeletonCard, Text } from "../ui";
import { BriefingCard, InsightCard } from "./coach";

const FILTERS = [
  { value: "live" as const, label: "Active" },
  { value: "bookmarked" as const, label: "Saved" },
  { value: "dismissed" as const, label: "Dismissed" },
];

/**
 * The coach: a narrative briefing over a ranked feed of insights.
 *
 * The feed is ordered by the backend's priority score, not by recency. That's
 * the whole point — a coach that lists twenty things chronologically surfaces
 * nothing, and the first item should be the one that matters today.
 */
/** `embedded` renders this page as a tab panel inside a hub (`/plan`,
 * `/insights`). The hub owns the <h1>, so the page must not render its own
 * PageHeader — two page titles on one route is a broken heading outline.
 * The Refresh control is not part of that title, though, so it still renders
 * when embedded — just in a plain row instead of a full PageHeader. */
export function CoachPage({ embedded }: { embedded?: boolean } = {}) {
  const [period, setPeriod] = useState<BriefingPeriod>("daily");
  const [filter, setFilter] = useState<"live" | "bookmarked" | "dismissed">("live");

  const { activeWorkspace } = useAuth();
  const currency = activeWorkspace?.tenant.base_currency ?? "USD";

  const { data: briefing, isLoading: briefingLoading } = useBriefing(period);
  const { data: insights, isLoading } = useInsights(filter === "live" ? undefined : filter);
  const generate = useGenerateInsights();
  const decide = useDecideInsight();

  const dismissed = filter === "dismissed";

  const refreshButton = (
    <Button
      variant="secondary"
      loading={generate.isPending}
      onClick={() => generate.mutate()}
      icon={<RefreshCw size={15} aria-hidden="true" />}
    >
      Refresh
    </Button>
  );

  return (
    <>
      {embedded ? (
        // The title is the hub's — this page still needs its own Refresh
        // control reachable, just without a second <h1> underneath it.
        <div className="lf-page-header-actions" style={{ justifyContent: "flex-end", marginBottom: "var(--lf-space-4)" }}>
          {refreshButton}
        </div>
      ) : (
        <PageHeader
          eyebrow="Meaning"
          title="Your coach"
          description="What's worth knowing about your money right now, and why."
          illustration="conversation"
          actions={refreshButton}
        />
      )}

      {generate.isError && (
        <Banner tone="danger">
          Couldn't refresh your insights
          {generate.error instanceof Error && generate.error.message ? `: ${generate.error.message}` : "."} Try again in a moment.
        </Banner>
      )}

      <div className="lf-coach-layout">
        <Card>
          <BriefingCard
            briefing={briefing}
            period={period}
            onPeriodChange={setPeriod}
            isLoading={briefingLoading}
          />
        </Card>

        <section aria-labelledby="insights-title">
          <div className="lf-coach-feed-head">
            <h2 className="lf-section-title" id="insights-title">
              Insights
            </h2>
            <SegmentedControl
              legend="Filter insights"
              options={FILTERS}
              value={filter}
              onChange={setFilter}
            />
          </div>

          {isLoading && <SkeletonCard />}

          {!isLoading && (insights?.length ?? 0) === 0 && (
            <Card>
              <EmptyState
                icon={Sparkles}
                illustration="conversation"
                title={
                  dismissed
                    ? "Nothing dismissed"
                    : filter === "bookmarked"
                      ? "Nothing saved yet"
                      : "Nothing needs your attention"
                }
                body={
                  dismissed
                    ? "Insights you dismiss are kept here in case you want them back."
                    : filter === "bookmarked"
                      ? "Bookmark an insight to keep it in front of you."
                      : "Your coach found nothing unusual. That's a real answer, not an empty screen."
                }
                tips={
                  filter === "live"
                    ? [
                        "The coach looks at budgets, bills, recurring charges and your projected balance.",
                        "Every insight explains why it appeared and shows the figures behind it.",
                        "Dismissing one stops it coming back, even when the condition persists.",
                      ]
                    : undefined
                }
              />
            </Card>
          )}

          <div className="lf-coach-feed">
            {(insights ?? []).map((insight) => (
              <InsightCard
                key={insight.id}
                insight={insight}
                currency={currency}
                // Dismissed insights are shown read-only: offering "dismiss"
                // on something already dismissed is a dead control.
                onDismiss={
                  dismissed ? undefined : (id) => decide.mutate({ insightId: id, decision: "dismiss" })
                }
                onBookmark={
                  dismissed ? undefined : (id) => decide.mutate({ insightId: id, decision: "bookmark" })
                }
              />
            ))}
          </div>

          {dismissed && (insights?.length ?? 0) > 0 && (
            <Text tone="tertiary" size="xs">
              Dismissed insights won't reappear in your feed, even if the situation continues.
            </Text>
          )}
        </section>
      </div>
    </>
  );
}
