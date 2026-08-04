import { Route } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError } from "../api/client";
import type {
  BaselineResponse,
  EventKindMeta,
  Projection,
  Scenario,
  ScenarioRun,
} from "../api/projections";
import { projectionsApi } from "../api/projections";
import { formatAmount, formatAmountSigned } from "../lib/money";
import {
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Figure,
  FormField,
  Grid,
  Inline,
  Input,
  PageHeader,
  SegmentedControl,
  SkeletonCard,
  Stack,
  Tabs,
  Text,
} from "../ui";
import {
  AssetMixChart,
  CashFlowProjectionChart,
  DebtTimelineChart,
  NetWorthChart,
} from "./projections/ProjectionCharts";
import { DecisionAssistant } from "./projections/DecisionAssistant";
import { RiskAndSimulation } from "./projections/RiskAndSimulation";
import { TwinPanel } from "./projections/TwinPanel";
import { ScenarioBuilder } from "./projections/ScenarioBuilder";

/** `SegmentedControl` is generic over a string union, so the horizon travels as
 * a string and is parsed at the one place it becomes a number. */
const HORIZONS = [
  { value: "60", label: "5 years" },
  { value: "120", label: "10 years" },
  { value: "240", label: "20 years" },
  { value: "480", label: "40 years" },
] as const;

type HorizonValue = (typeof HORIZONS)[number]["value"];

const CHART_TABS = [
  { value: "net-worth", label: "Net worth" },
  { value: "cash", label: "Cash flow" },
  { value: "debt", label: "Debt" },
  { value: "assets", label: "Where it sits" },
] as const;

type ChartTab = (typeof CHART_TABS)[number]["value"];

/** The three questions the page answers, in the order people ask them: where
 * is this going, what should I do, and how sure are we. */
const SECTIONS = [
  { value: "projection", label: "Where this goes" },
  { value: "decisions", label: "Should I?" },
  { value: "confidence", label: "How sure" },
  { value: "twin", label: "What it knows" },
] as const;

type Section = (typeof SECTIONS)[number]["value"];

function monthLabel(months: number | null, asOf: string): string {
  if (months === null) return "not within this window";
  const start = new Date(`${asOf}T00:00:00`);
  start.setMonth(start.getMonth() + months);
  return start.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

/** The summary strip above the charts. Deliberately leads with the trough
 * rather than the closing balance: the month you go negative is the one that
 * costs money, and a healthy end-state routinely hides one. */
function ProjectionSummary({
  projection,
  currency,
}: {
  projection: Projection;
  currency: string;
}) {
  const s = projection.summary;
  const goesNegative = s.first_negative_month !== null;
  return (
    <Grid cols={4}>
      <Figure
        label="Net worth at the end"
        value={formatAmountSigned(s.closing_net_worth_minor, currency)}
        certainty="projected"
      />
      <Figure
        label="Lowest your cash gets"
        value={formatAmountSigned(s.lowest_liquid_minor, currency)}
        tone={goesNegative ? "critical" : "default"}
        hint={monthLabel(s.lowest_liquid_month, projection.as_of)}
        certainty="projected"
      />
      <Figure
        label="Debt free"
        value={s.debt_free_month === null ? "—" : monthLabel(s.debt_free_month, projection.as_of)}
        hint={s.debt_free_month === null ? "not within this window" : undefined}
        certainty="projected"
      />
      <Figure
        label="Interest paid"
        value={formatAmount(s.total_interest_paid_minor, currency)}
        certainty="projected"
      />
    </Grid>
  );
}

function Assumptions({ projection }: { projection: Projection }) {
  return (
    <Card title="What this assumes">
      <ul className="lf-assumption-list">
        {projection.assumptions.map((a) => (
          <li key={a}>
            <Text size="sm" tone="secondary">
              {a}
            </Text>
          </li>
        ))}
      </ul>
      {projection.warnings.length > 0 && (
        <Banner tone="warning">
          {projection.warnings.map((w) => (
            <Text key={w} size="sm" style={{ display: "block" }}>
              {w}
            </Text>
          ))}
        </Banner>
      )}
    </Card>
  );
}

function ChartDeck({
  projection,
  baseline,
  currency,
}: {
  projection: Projection;
  baseline?: Projection;
  currency: string;
}) {
  // `Tabs` renders the tablist only; the panel is the parent's job.
  const [tab, setTab] = useState<ChartTab>("net-worth");
  return (
    <Stack gap={3}>
      <Tabs<ChartTab> label="Projection view" value={tab} onChange={setTab} tabs={[...CHART_TABS]} />
      {tab === "net-worth" && (
        <NetWorthChart projection={projection} baseline={baseline} currency={currency} />
      )}
      {tab === "cash" && <CashFlowProjectionChart projection={projection} currency={currency} />}
      {tab === "debt" && <DebtTimelineChart projection={projection} currency={currency} />}
      {tab === "assets" && <AssetMixChart projection={projection} currency={currency} />}
    </Stack>
  );
}

export function ProjectionsPage() {
  const [horizonValue, setHorizonValue] = useState<HorizonValue>("120");
  const horizon = Number(horizonValue);
  const [section, setSection] = useState<Section>("projection");
  const [baseline, setBaseline] = useState<BaselineResponse | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [catalogue, setCatalogue] = useState<EventKindMeta[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [run, setRun] = useState<ScenarioRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");

  const selected = useMemo(
    () => scenarios.find((s) => s.id === selectedId) ?? null,
    [scenarios, selectedId],
  );

  const loadBaseline = useCallback(async () => {
    try {
      setBaseline(await projectionsApi.baseline(horizon));
      setError(null);
    } catch (err) {
      setBaseline(null);
      setError(
        err instanceof ApiError ? err.detail : "Couldn't build a projection from this workspace.",
      );
    }
  }, [horizon]);

  const loadScenarios = useCallback(async () => {
    const { results } = await projectionsApi.listScenarios();
    setScenarios(results);
    return results;
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      await loadBaseline();
      try {
        const [{ results: kinds }] = await Promise.all([projectionsApi.eventCatalogue()]);
        const list = await loadScenarios();
        if (cancelled) return;
        setCatalogue(kinds);
        if (list.length && !selectedId) setSelectedId(list[0].id);
      } catch {
        /* the baseline error above already explains an empty workspace */
      }
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadBaseline, loadScenarios]);

  useEffect(() => {
    if (!selectedId) {
      setRun(null);
      return;
    }
    let cancelled = false;
    projectionsApi
      .run(selectedId)
      .then((r) => {
        if (!cancelled) setRun(r);
      })
      .catch(() => {
        if (!cancelled) setRun(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, scenarios]);

  const createScenario = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    const created = await projectionsApi.createScenario({
      name: newName.trim(),
      horizon_months: horizon,
    });
    setNewName("");
    await loadScenarios();
    setSelectedId(created.id);
  };

  const refresh = useCallback(async () => {
    const list = await loadScenarios();
    if (selectedId && !list.some((s) => s.id === selectedId)) setSelectedId(list[0]?.id ?? null);
  }, [loadScenarios, selectedId]);

  if (loading) {
    return (
      <>
        <PageHeader title="Projections" description="Where this is heading, and what would change it." />
        <SkeletonCard />
      </>
    );
  }

  if (error || !baseline) {
    return (
      <>
        <PageHeader title="Projections" description="Where this is heading, and what would change it." />
        <EmptyState
          icon={Route}
          title="Nothing to project yet"
          body={error ?? "Add an account and a little history first."}
        />
      </>
    );
  }

  const currency = baseline.position.currency;
  const shown = run ? run.scenario : baseline.projection;
  const comparison = run ? run.baseline : undefined;

  return (
    <>
      <PageHeader
        title="Projections"
        description="Where this is heading if nothing changes — and what each decision would do to it."
        actions={
          <SegmentedControl<HorizonValue>
            legend="Projection horizon"
            options={[...HORIZONS]}
            value={horizonValue}
            onChange={setHorizonValue}
          />
        }
      />

      <Tabs<Section>
        label="Projection section"
        value={section}
        onChange={setSection}
        tabs={[...SECTIONS]}
      />

      {section === "decisions" && (
        <div className="lf-section-body">
          <DecisionAssistant />
        </div>
      )}

      {section === "confidence" && (
        <div className="lf-section-body">
          <RiskAndSimulation months={horizon} />
        </div>
      )}

      {section === "twin" && (
        <div className="lf-section-body">
          <TwinPanel />
        </div>
      )}

      {section !== "projection" ? null : (
      <Stack gap={5}>
        <section>
          <ProjectionSummary projection={shown} currency={currency} />
        </section>

        {run && (
          <Banner tone="info">
            <Text size="sm">
              Showing <strong>{run.scenario_name}</strong> against your current path. Net worth
              ends {formatAmountSigned(run.delta.net_worth_minor, currency)} different; the
              low point moves by {formatAmountSigned(run.delta.trough_minor, currency)}.
            </Text>
          </Banner>
        )}

        <ChartDeck projection={shown} baseline={comparison} currency={currency} />

        <Grid cols={2}>
          <Card title="Scenarios">
            {scenarios.length === 0 ? (
              <Text size="sm" tone="secondary">
                No scenarios yet. Name one below — a scenario changes nothing about your real
                money, so there is no cost to being wrong.
              </Text>
            ) : (
              <ul className="lf-scenario-list">
                {scenarios.map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      className="lf-scenario-pick"
                      aria-pressed={s.id === selectedId}
                      onClick={() => setSelectedId(s.id === selectedId ? null : s.id)}
                    >
                      <span className="lf-scenario-pick-name">{s.name}</span>
                      <Inline gap={2}>
                        <Badge tone={s.status === "active" ? "success" : "neutral"}>
                          {s.status}
                        </Badge>
                        <Text size="xs" tone="tertiary">
                          {s.events.length} event{s.events.length === 1 ? "" : "s"}
                        </Text>
                      </Inline>
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <form onSubmit={createScenario} className="lf-scenario-new">
              <FormField label="New scenario" htmlFor="scenario-name">
                <Input
                  id="scenario-name"
                  value={newName}
                  placeholder="Buy a house in 2028"
                  onChange={(e) => setNewName(e.target.value)}
                />
              </FormField>
              <Button type="submit" disabled={!newName.trim()}>
                Create
              </Button>
            </form>

            {selected && (
              <Inline gap={2} className="lf-scenario-actions">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={async () => {
                    await projectionsApi.duplicateScenario(selected.id);
                    await refresh();
                  }}
                >
                  Duplicate
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={async () => {
                    await projectionsApi.archiveScenario(selected.id);
                    await refresh();
                  }}
                >
                  Archive
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={async () => {
                    await projectionsApi.deleteScenario(selected.id);
                    await refresh();
                  }}
                >
                  Delete
                </Button>
              </Inline>
            )}
          </Card>

          {selected ? (
            <ScenarioBuilder scenario={selected} catalogue={catalogue} onChanged={refresh} />
          ) : (
            <Card title="What happens">
              <Text size="sm" tone="secondary">
                Pick a scenario to add life events to it — a house, a child, a job change, a
                career break.
              </Text>
            </Card>
          )}
        </Grid>

        <Assumptions projection={shown} />
      </Stack>
      )}
    </>
  );
}
