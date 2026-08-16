import { Route } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import type {
  BaselineResponse,
  CashflowStackLine,
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
  ConfirmAction,
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
import { scenarioHints } from "./projections/scenarioHints";

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

function startsMonthLabel(iso: string): string {
  const [year, month] = iso.split("-").map(Number);
  if (!year || !month) return iso;
  return new Date(year, month - 1, 1).toLocaleDateString(undefined, {
    month: "short",
    year: "numeric",
  });
}

function CashflowStack({
  lines,
  currency,
  incomeMinor,
  expensesMinor,
}: {
  lines: CashflowStackLine[];
  currency: string;
  incomeMinor: number;
  expensesMinor: number;
}) {
  const incoming = lines.filter((l) => l.direction === "in");
  const outgoing = lines.filter((l) => l.direction === "out");
  return (
    <Card title="What each month already counts">
      <Text size="sm" tone="secondary">
        Recurring income, recurring charges, income sources, and bills already
        on the books. A home purchase can replace rent by filling in the cost it
        stops — we never invent a number that is not on this list.
      </Text>
      <Grid cols={2}>
        <Figure
          label="Promised income / mo"
          value={formatAmount(incomeMinor, currency)}
        />
        <Figure
          label="Promised spending / mo"
          value={formatAmount(expensesMinor, currency)}
        />
      </Grid>
      <Grid cols={2}>
        <Stack gap={2}>
          <Text size="xs" tone="tertiary">
            Coming in
          </Text>
          {incoming.length === 0 ? (
            <Text size="sm" tone="tertiary">
              No recurring income in this currency. Add a paycheck under{" "}
              <Link to="/recurring">Recurring</Link> or{" "}
              <Link to="/income">Income</Link>.
            </Text>
          ) : (
            <ul className="lf-assumption-list">
              {incoming.map((line) => (
                <li key={line.id}>
                  <Text size="sm">
                    {line.label}{" "}
                    <Text as="span" tone="secondary" size="sm">
                      {formatAmount(line.monthly_minor, currency)}
                      {line.periodical ? "" : " / mo"}
                    </Text>
                    {line.current === false && line.starts_on ? (
                      <Text as="span" tone="tertiary" size="xs">
                        {" "}
                        · starts {startsMonthLabel(line.starts_on)}
                      </Text>
                    ) : null}
                  </Text>
                </li>
              ))}
            </ul>
          )}
        </Stack>
        <Stack gap={2}>
          <Text size="xs" tone="tertiary">
            Going out
          </Text>
          {outgoing.length === 0 ? (
            <Text size="sm" tone="tertiary">
              No recurring expenses in this currency. Add rent and bills under{" "}
              <Link to="/recurring">Recurring</Link>.
            </Text>
          ) : (
            <ul className="lf-assumption-list">
              {outgoing.map((line) => (
                <li key={line.id}>
                  <Text size="sm">
                    {line.label}{" "}
                    <Text as="span" tone="secondary" size="sm">
                      {formatAmount(line.monthly_minor, currency)}
                      {line.periodical ? "" : " / mo"}
                    </Text>
                    {line.current === false && line.starts_on ? (
                      <Text as="span" tone="tertiary" size="xs">
                        {" "}
                        · starts {startsMonthLabel(line.starts_on)}
                      </Text>
                    ) : null}
                    {line.stoppable ? (
                      <Text as="span" tone="tertiary" size="xs">
                        {" "}
                        · can stop if you buy a home
                      </Text>
                    ) : null}
                  </Text>
                </li>
              ))}
            </ul>
          )}
        </Stack>
      </Grid>
    </Card>
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

  const applySuggestion = async (name: string, kind: string, params: Record<string, unknown>) => {
    const created = await projectionsApi.createScenario({ name, horizon_months: horizon });
    await projectionsApi.addEvent(created.id, { kind, start_month: 1, params });
    await loadScenarios();
    setSelectedId(created.id);
    setSection("projection");
  };

  if (loading) {
    return (
      <>
        <PageHeader
          eyebrow="Trajectory"
          title="Projections"
          description="Where this is heading, and what would change it."
          illustration="horizon"
        />
        <SkeletonCard />
      </>
    );
  }

  if (error || !baseline) {
    return (
      <>
        <PageHeader
          eyebrow="Trajectory"
          title="Projections"
          description="Where this is heading, and what would change it."
          illustration="horizon"
        />
        <EmptyState
          icon={Route}
          illustration="horizon"
          title="Nothing to project yet"
          body={error ?? "Add an account and a little history first."}
        />
      </>
    );
  }

  const currency = baseline.position.currency;
  const shown = run ? run.scenario : baseline.projection;
  const comparison = run ? run.baseline : undefined;
  const hints = scenarioHints(baseline.position, baseline.cashflow_stack ?? []);

  return (
    <>
      <PageHeader
        eyebrow="Trajectory"
        title="Projections"
        description="Where this is heading if nothing changes — and what each decision would do to it."
        illustration="horizon"
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
          <DecisionAssistant
            position={baseline?.position}
            stack={baseline?.cashflow_stack}
          />
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

        <CashflowStack
          lines={baseline.cashflow_stack ?? []}
          currency={currency}
          incomeMinor={baseline.position.monthly_net_income_minor}
          expensesMinor={baseline.position.monthly_expenses_minor}
        />

        <Grid cols={2}>
          <Card title="Scenarios">
            {(hints.surplusMinor > 0 || hints.debtLabel) && (
              <Stack gap={2} style={{ marginBottom: "var(--lf-space-3)" }}>
                <Text size="sm" tone="secondary">
                  Start from a decision this ledger can already measure, rather than a blank form.
                </Text>
                <Inline gap={2}>
                  {hints.surplusMinor > 0 && (
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        applySuggestion("Invest the monthly surplus", "invest_more", {
                          monthly_amount_minor: hints.surplusMinor,
                        })
                      }
                    >
                      Invest {formatAmount(hints.surplusMinor, currency)} / mo
                    </Button>
                  )}
                  {hints.surplusMinor > 0 && hints.debtLabel && (
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() =>
                        applySuggestion(`Extra on ${hints.debtLabel}`, "debt_payoff", {
                          amount_minor: hints.surplusMinor,
                          debt_label: hints.debtLabel,
                        })
                      }
                    >
                      Extra on {hints.debtLabel}
                    </Button>
                  )}
                </Inline>
              </Stack>
            )}
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
                <ConfirmAction
                  label="Delete"
                  confirmLabel="Delete"
                  cancelLabel="Keep"
                  size="sm"
                  onConfirm={async () => {
                    await projectionsApi.deleteScenario(selected.id);
                    await refresh();
                  }}
                />
              </Inline>
            )}
          </Card>

          {selected ? (
            <ScenarioBuilder
              scenario={selected}
              catalogue={catalogue}
              onChanged={refresh}
              hints={hints}
            />
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
