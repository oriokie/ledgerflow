import { Target } from "lucide-react";
import { useMemo, useState } from "react";
import {
  useArchiveGoal,
  useGoalForecasts,
  useGoalRecommendations,
  useGoals,
} from "../hooks/useGoals";
import { Button, Card, Checkbox, EmptyState, Grid, PageHeader, SkeletonCard } from "../ui";
import { CreateGoalForm, GoalCard, GoalRecommendations, GoalsSummary } from "./goals";
import { sortGoals } from "./goals/goalMath";
import { useOpenOnParam } from "../hooks/useOpenOnParam";

export function GoalsPage() {
  const [includeArchived, setIncludeArchived] = useState(false);
  const { data: goals, isLoading } = useGoals(includeArchived);
  const { data: forecasts } = useGoalForecasts();
  const { data: goalRecommendations } = useGoalRecommendations();
  // Keyed lookup so each card gets its forecast without an O(n²) scan.
  const forecastById = useMemo(
    () => new Map((forecasts ?? []).map((f) => [f.goal_id, f])),
    [forecasts],
  );
  const archiveGoal = useArchiveGoal();
  const [showCreate, setShowCreate] = useOpenOnParam();

  const sorted = sortGoals(goals ?? []);
  const hasGoals = (goals?.length ?? 0) > 0;

  return (
    <>
      <PageHeader
        eyebrow="Savings"
        title="Goals"
        actions={
          <Button variant="primary" onClick={() => setShowCreate((v) => !v)}>
            {showCreate ? "Close" : "New goal"}
          </Button>
        }
      />

      {showCreate && <CreateGoalForm onCreated={() => setShowCreate(false)} onCancel={() => setShowCreate(false)} />}

      {/* Renders nothing when the engine has no honest suggestion to make. */}
      {!showCreate && (
        <GoalRecommendations
          recommendations={goalRecommendations ?? []}
          onAccept={() => setShowCreate(true)}
        />
      )}

      {isLoading && <SkeletonCard />}

      {goals && goals.length === 0 && !showCreate && (
        <Card>
          <EmptyState
            icon={Target}
            illustration="success"
            title="Set your first savings goal"
            body="Name what you're saving for, set a target, and watch your progress fill up as you contribute."
            tips={[
              "Give a goal a target date and LedgerFlow works out the monthly pace.",
              "Contribute from any account — the goal tracks the total, not the source.",
              "Milestones mark 25 / 50 / 75% so long saves stay motivating.",
            ]}
            action={
              <Button variant="primary" onClick={() => setShowCreate(true)}>
                Create a goal
              </Button>
            }
          />
        </Card>
      )}

      {hasGoals && (
        <div className="lf-dash-section" style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-4)" }}>
          <GoalsSummary goals={goals ?? []} />

          <Grid cols={2} gap={4}>
            {sorted.map((goal) => (
              <GoalCard
                key={goal.id}
                goal={goal}
                forecast={forecastById.get(goal.id)}
                onArchive={(id) => archiveGoal.mutate(id)}
              />
            ))}
          </Grid>

          <div>
            <Checkbox
              label="Show archived goals"
              checked={includeArchived}
              onChange={(e) => setIncludeArchived(e.target.checked)}
            />
          </div>
        </div>
      )}
    </>
  );
}
