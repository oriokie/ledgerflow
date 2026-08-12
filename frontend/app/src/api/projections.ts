import { api } from "./client";

/** Rates travel as decimal strings so a 0.07 typed into a form round-trips as
 * "0.0700" rather than 0.06999999999999999. */
export interface AssumptionSet {
  id: string;
  name: string;
  is_default: boolean;
  notes: string;
  annual_inflation: string;
  annual_salary_growth: string;
  annual_investment_return: string;
  annual_cash_return: string;
  effective_tax_rate: string;
  annual_property_growth: string;
}

export type ScenarioStatus = "draft" | "active" | "archived";
export type ScenarioVisibility = "private" | "household";

export interface ScenarioEvent {
  id: string;
  kind: string;
  label: string;
  start_month: number;
  params: Record<string, unknown>;
  is_enabled: boolean;
  sort_order: number;
}

export interface Scenario {
  id: string;
  name: string;
  description: string;
  status: ScenarioStatus;
  visibility: ScenarioVisibility;
  horizon_months: number;
  assumption_set_id: string | null;
  duplicated_from_id: string | null;
  created_at: string;
  updated_at: string;
  events: ScenarioEvent[];
}

export interface ProjectionPoint {
  month: number;
  on: string;
  income_minor: number;
  expenses_minor: number;
  debt_payments_minor: number;
  net_cashflow_minor: number;
  liquid_minor: number;
  investment_minor: number;
  other_assets_minor: number;
  debt_balance_minor: number;
  net_worth_minor: number;
  events: string[];
}

export interface ProjectionSummary {
  opening_net_worth_minor: number;
  closing_net_worth_minor: number;
  lowest_liquid_minor: number;
  lowest_liquid_month: number;
  first_negative_month: number | null;
  first_negative_on: string | null;
  debt_free_month: number | null;
  total_interest_paid_minor: number;
}

export interface Projection {
  currency: string;
  as_of: string;
  months: number;
  summary: ProjectionSummary;
  points: ProjectionPoint[];
  assumptions: string[];
  warnings: string[];
}

export interface PositionDebt {
  label: string;
  balance_minor: number;
  annual_rate: number;
  monthly_payment_minor: number;
}

export interface Position {
  currency: string;
  as_of: string;
  liquid_minor: number;
  investment_minor: number;
  other_assets_minor: number;
  monthly_net_income_minor: number;
  monthly_expenses_minor: number;
  net_worth_minor: number;
  debts: PositionDebt[];
}

export interface CashflowStackLine {
  id: string;
  kind: string;
  direction: "in" | "out";
  label: string;
  monthly_minor: number;
  stoppable: boolean;
}

export interface BaselineResponse {
  position: Position;
  projection: Projection;
  cashflow_stack?: CashflowStackLine[];
}

export interface ScenarioRun {
  scenario_id: string;
  scenario_name: string;
  baseline: Projection;
  scenario: Projection;
  delta: { net_worth_minor: number; trough_minor: number };
  notes: string[];
}

export interface ComparisonResponse {
  as_of: string;
  currency: string;
  runs: ScenarioRun[];
  notes: string[];
}

export interface EventParamSpec {
  name: string;
  required: boolean;
  type: string;
  default: unknown;
}

export interface EventKindMeta {
  kind: string;
  label: string;
  params: EventParamSpec[];
}

export const projectionsApi = {
  /** Where the current trajectory leads if nothing changes — the question
   * every scenario is measured against. 409 when the workspace is empty. */
  baseline: (months = 120) => api.get<BaselineResponse>(`/projections/baseline/?months=${months}`),

  assumptions: () => api.get<AssumptionSet>("/projections/assumptions/"),
  updateAssumptions: (body: Partial<AssumptionSet>) =>
    api.patch<AssumptionSet>("/projections/assumptions/", body),

  /** The scenario builder renders its forms from this rather than a hard-coded
   * copy that drifts from the backend's schema. */
  eventCatalogue: () =>
    api.get<{ results: EventKindMeta[] }>("/projections/event-catalogue/"),

  listScenarios: (status?: ScenarioStatus) =>
    api.get<{ results: Scenario[] }>(
      `/projections/scenarios/${status ? `?status=${status}` : ""}`,
    ),
  getScenario: (id: string) => api.get<Scenario>(`/projections/scenarios/${id}/`),
  createScenario: (body: {
    name: string;
    description?: string;
    horizon_months?: number;
    status?: ScenarioStatus;
    visibility?: ScenarioVisibility;
  }) => api.post<Scenario>("/projections/scenarios/", body),
  updateScenario: (id: string, body: Partial<Scenario>) =>
    api.patch<Scenario>(`/projections/scenarios/${id}/`, body),
  deleteScenario: (id: string) => api.delete<void>(`/projections/scenarios/${id}/`),
  duplicateScenario: (id: string, name?: string) =>
    api.post<Scenario>(`/projections/scenarios/${id}/duplicate/`, name ? { name } : {}),
  archiveScenario: (id: string) =>
    api.post<Scenario>(`/projections/scenarios/${id}/archive/`, {}),

  addEvent: (
    scenarioId: string,
    body: { kind: string; start_month?: number; params?: Record<string, unknown>; label?: string },
  ) => api.post<ScenarioEvent>(`/projections/scenarios/${scenarioId}/events/`, body),
  updateEvent: (scenarioId: string, eventId: string, body: Partial<ScenarioEvent>) =>
    api.patch<ScenarioEvent>(`/projections/scenarios/${scenarioId}/events/${eventId}/`, body),
  deleteEvent: (scenarioId: string, eventId: string) =>
    api.delete<void>(`/projections/scenarios/${scenarioId}/events/${eventId}/`),

  run: (id: string) => api.get<ScenarioRun>(`/projections/scenarios/${id}/run/`),
  compare: (ids: string[]) =>
    api.post<ComparisonResponse>("/projections/scenarios/compare/", { scenario_ids: ids }),

  calculator: <T>(slug: string, body: Record<string, unknown>) =>
    api.post<T>(`/projections/calculators/${slug}/`, body),
};

// ---------------------------------------------------------------------------
// Phase 2 — decision support
// ---------------------------------------------------------------------------
export interface Percentiles {
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
}

export interface SimulationBand extends Percentiles {
  month: number;
}

export interface SimulationResult {
  currency: string;
  trials: number;
  seed: number;
  months: number;
  closing_net_worth: Percentiles;
  trough: Percentiles;
  success_probability: number;
  failure_probability: number;
  median_failure_month: number | null;
  bands: SimulationBand[];
  assumptions: string[];
  deterministic: Projection | null;
}

export interface Swing {
  lever: string;
  label: string;
  low_value: number;
  high_value: number;
  low_closing_minor: number;
  high_closing_minor: number;
  baseline_closing_minor: number;
  spread_minor: number;
  direction: "higher is better" | "higher is worse";
}

export interface SensitivityResult {
  currency: string;
  months: number;
  baseline_closing_minor: number;
  swings: Swing[];
  notes: string[];
}

export interface WhatIfResult {
  question: string;
  changed: string;
  baseline_closing_minor: number;
  changed_closing_minor: number;
  baseline_trough_minor: number;
  changed_trough_minor: number;
  introduces_shortfall: boolean;
  delta_minor: number;
  notes: string[];
}

export interface RiskFactor {
  key: string;
  label: string;
  score: number;
  value: number;
  detail: string;
  remedy: string;
}

export interface RiskProfile {
  currency: string;
  resilience: number;
  headline: string;
  factors: RiskFactor[];
  notes: string[];
}

export type Verdict = "yes" | "yes_with_care" | "tight" | "no" | "unknown";

export interface DecisionFinding {
  label: string;
  text: string;
  amount_minor: number | null;
  months: number | null;
  percent: number | null;
}

export interface DecisionResult {
  question: string;
  verdict: Verdict;
  headline: string;
  confidence: "measured" | "mixed" | "assumed";
  because: DecisionFinding[];
  costs: DecisionFinding[];
  risks: DecisionFinding[];
  alternatives: DecisionFinding[];
  assumptions: string[];
  explanation: { paragraphs: string[]; llm_used: boolean; rejected_reason: string };
  currency: string;
}

export interface QuestionField {
  name: string;
  required: boolean;
  type: string;
}

export interface QuestionMeta {
  slug: string;
  question: string;
  fields: QuestionField[];
}

export const advisorApi = {
  simulate: (body: {
    months?: number;
    trials?: number;
    seed?: number;
    scenario_id?: string | null;
  }) => api.post<SimulationResult>("/projections/simulate/", body),

  sensitivity: (months = 120) =>
    api.get<SensitivityResult>(`/projections/sensitivity/?months=${months}`),

  whatIf: (body: {
    months?: number;
    inflation?: number;
    investment_return?: number;
    salary_growth?: number;
    rate_shift?: number;
  }) => api.post<WhatIfResult>("/projections/what-if/", body),

  risk: () => api.get<RiskProfile>("/projections/risk/"),

  /** The scenario builder's sibling: the question forms render from this. */
  questions: () => api.get<{ results: QuestionMeta[] }>("/projections/questions/"),

  ask: (slug: string, body: Record<string, unknown>) =>
    api.post<DecisionResult>(`/projections/questions/${slug}/`, body),
};

// ---------------------------------------------------------------------------
// Phase 4 — the digital twin
// ---------------------------------------------------------------------------
export interface TwinParameter {
  key: string;
  label: string;
  measured: number | null;
  prior: number;
  months_observed: number;
  confidence: "none" | "weak" | "moderate" | "strong";
  detail: string;
  effective: number;
  differs_from_prior: boolean;
}

export interface Twin {
  currency: string;
  as_of: string;
  months_observed: number;
  confidence: "none" | "weak" | "moderate" | "strong";
  parameters: TwinParameter[];
  notes: string[];
}

export interface KindAccuracy {
  kind: string;
  label: string;
  samples: number;
  median_error: number | null;
  /** Can be "worse" — a report that can only improve is not a measurement. */
  trend: "improving" | "steady" | "worse" | null;
  detail: string;
}

export interface CalibrationReport {
  as_of: string;
  total_scored: number;
  kinds: KindAccuracy[];
  headline: string;
  notes: string[];
  overall_median_error: number | null;
}

export interface AskAnswer {
  answered: boolean;
  question: string;
  matched: string | null;
  understood_as?: string;
  llm_used: boolean;
  missing?: string[];
  detail?: string;
  available?: Record<string, string>;
  verdict?: Verdict;
  headline?: string;
  confidence?: "measured" | "mixed" | "assumed";
  because?: DecisionFinding[];
  costs?: DecisionFinding[];
  risks?: DecisionFinding[];
  alternatives?: DecisionFinding[];
  assumptions?: string[];
  explanation?: { paragraphs: string[]; llm_used: boolean; rejected_reason: string };
  currency?: string;
}

export const twinApi = {
  get: () => api.get<Twin>("/twin/"),
  calibration: () => api.get<CalibrationReport>("/twin/calibration/"),
  recordForecast: () =>
    api.post<{ scored: number; recorded: unknown[]; detail: string }>("/twin/calibration/", {}),
  ask: (question: string, useLlm = true) =>
    api.post<AskAnswer>("/twin/ask/", { question, use_llm: useLlm }),
};
