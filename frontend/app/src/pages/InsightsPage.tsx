import { Lightbulb, Lock, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { useCategories } from "../hooks/useFinance";
import { useAiEnabled } from "../hooks/useEntitlements";
import {
  useAnomalies,
  useCashRunway,
  useMilestones,
  useDecideSuggestion,
  useHealthScore,
  useRecommendations,
  useSuggestions,
} from "../hooks/useIntelligence";
import { Button, Card, EmptyState, Grid, SkeletonCard, Stack } from "../ui";
import { AnomalyList, CashRunwayCard, GuidanceCard, HealthSummary, InsightsGreeting, MilestoneList, SuggestionCard } from "./insights";

export function InsightsPage() {
  const { aiEnabled } = useAiEnabled();
  const { data: health, isLoading: healthLoading } = useHealthScore(aiEnabled);
  const { data: recommendations } = useRecommendations(aiEnabled);
  const { data: anomalies } = useAnomalies(aiEnabled);
  const { data: suggestions } = useSuggestions("pending", aiEnabled);
  const { data: runway } = useCashRunway(aiEnabled);
  const { data: categories } = useCategories();
  const { data: milestones } = useMilestones();
  const decide = useDecideSuggestion();

  const categoryById = new Map((categories ?? []).map((c) => [c.id, c.name]));
  const guidance = recommendations ?? [];

  if (!aiEnabled) {
    return (
      <Card>
        <EmptyState
          icon={Lock}
          title="AI insights are a premium feature"
          body="Upgrade your plan to unlock personalized guidance, spending anomaly detection, and financial health scoring."
          action={
            <Link to="/billing">
              <Button variant="primary">See plans</Button>
            </Link>
          }
        />
      </Card>
    );
  }

  return (
    <>
      <InsightsGreeting health={health} guidanceCount={guidance.length} />

      <div style={{ marginBottom: "var(--lf-space-4)" }}>
        <CashRunwayCard runway={runway} />
      </div>

      <div className="lf-dash-section" style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-4)" }}>
        {healthLoading && <SkeletonCard />}

        {/* Guidance — the heart of the page */}
        {guidance.length > 0 ? (
          <Stack gap={3}>
            {guidance.map((rec, i) => (
              <GuidanceCard key={`${rec.kind}-${i}`} rec={rec} />
            ))}
          </Stack>
        ) : (
          <Card>
            <EmptyState
              icon={ShieldCheck}
              title="You're all set for now"
              body="There's nothing that needs action today. We'll surface friendly suggestions here whenever something's worth a look."
            />
          </Card>
        )}

        {/* Health, made human */}
        {health && <HealthSummary health={health} />}

        {/* What has already happened. Sits below the health score and above the
            things needing attention: it is context for both, and it is the only
            part of this page that is purely a record. */}
        {milestones && milestones.length > 0 && (
          <Card title="Milestones" eyebrow="Already behind you">
            <MilestoneList milestones={milestones} />
          </Card>
        )}

        {/* Worth a look */}
        {anomalies && anomalies.length > 0 && (
          <Card title="Worth a look" eyebrow="A few things we noticed">
            <AnomalyList anomalies={anomalies} />
          </Card>
        )}

        {/* Quick categorizations */}
        {suggestions && suggestions.length > 0 && (
          <section>
            <p className="lf-insights-section-title">Quick categorizations</p>
            <Grid cols={2} gap={4}>
              {suggestions.map((s) => (
                <SuggestionCard
                  key={s.id}
                  suggestion={s}
                  categoryName={categoryById.get(s.suggested_category_id)}
                  pending={decide.isPending}
                  onAccept={() => decide.mutate({ id: s.id, decision: "accept" })}
                  onReject={() => decide.mutate({ id: s.id, decision: "reject" })}
                />
              ))}
            </Grid>
          </section>
        )}

        {!healthLoading && !health && guidance.length === 0 && (!anomalies || anomalies.length === 0) && (!suggestions || suggestions.length === 0) && (
          <Card>
            <EmptyState
              icon={Lightbulb}
              title="Insights are warming up"
              body="As you add accounts and transactions, LedgerFlow learns your patterns and starts offering guidance here."
            />
          </Card>
        )}
      </div>
    </>
  );
}
