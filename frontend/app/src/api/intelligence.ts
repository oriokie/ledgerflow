import { api } from "./client";
import type {
  Anomaly,
  Briefing,
  BriefingPeriod,
  CashRunway,
  Forecast,
  HealthScore,
  Insight,
  AskResult,
  LLMSettings,
  Milestone,
  NetWorthHistoryPoint,
  Recommendation,
  SpendingTrendPoint,
} from "./types";

/** The AI coach. Reading and generating are separate calls on purpose: opening
 * the dashboard should never block on a full recompute. */
export const coachApi = {
  /** Live feed, most important first. `status` filters to bookmarked,
   * dismissed, or all. */
  insights: (status?: "bookmarked" | "dismissed" | "all") =>
    api.get<Insight[]>(`/intelligence/insights/${status ? `?status=${status}` : ""}`),

  /** Re-runs the coach. Idempotent — existing conditions are refreshed, not
   * duplicated, and dismissed insights stay dismissed. */
  generate: () => api.post<Insight[]>("/intelligence/insights/generate/", {}),

  decide: (insightId: string, decision: "dismiss" | "bookmark" | "seen" | "acted") =>
    api.post<Insight>(`/intelligence/insights/${insightId}/${decision}/`, {}),

  /** Read-only view of the deployment's AI configuration. */
  llmSettings: () => api.get<LLMSettings>("/intelligence/llm-settings/"),

  /** Admin-only — the API rejects anything less. */
  setTenantAiEnabled: (enabled: boolean) =>
    api.patch<{ tenant_ai_enabled: boolean }>("/intelligence/llm-settings/", {
      tenant_ai_enabled: enabled,
    }),

  briefing: (period: BriefingPeriod) =>
    api.get<Briefing>(`/intelligence/briefing/${period}/`),
};

export const intelligenceApi = {
  healthScore: () => api.get<HealthScore>("/intelligence/health-score/"),
  recommendations: () => api.get<Recommendation[]>("/intelligence/recommendations/"),
  anomalies: () => api.get<Anomaly[]>("/intelligence/anomalies/"),
  forecast: () => api.get<Forecast>("/intelligence/forecast/"),
  cashRunway: () => api.get<CashRunway>("/intelligence/cash-runway/"),
  /** Dated achievements, newest first. Empty is a normal answer. */
  milestones: () => api.get<Milestone[]>("/intelligence/milestones/"),

  /** Interpret a question as a ledger filter. Returns `{query: null}` when
   * nothing usable came of it — the caller falls back to plain search. */
  ask: (question: string) => api.post<AskResult>("/intelligence/ask/", { question }),

  netWorthHistory: (months = 12) =>
    api.get<NetWorthHistoryPoint[]>(`/intelligence/net-worth-history/?months=${months}`),
  spendingTrend: (months = 6) =>
    api.get<SpendingTrendPoint[]>(`/intelligence/spending-trend/?months=${months}`),
};

// ---------------------------------------------------------------- extended
import type { AutomationRule, CategorizationSuggestion } from "./types";

export const suggestionsApi = {
  list: (status?: string) =>
    api.get<CategorizationSuggestion[]>(`/intelligence/suggestions/${status ? `?status=${status}` : ""}`),
  decide: (suggestionId: string, decision: "accept" | "reject") =>
    api.post<CategorizationSuggestion>(`/intelligence/suggestions/${suggestionId}/${decision}/`),
};

export const automationApi = {
  list: () => api.get<AutomationRule[]>("/intelligence/automation-rules/"),
  get: (ruleId: string) => api.get<AutomationRule>(`/intelligence/automation-rules/${ruleId}/`),
  create: (payload: {
    name: string;
    conditions: AutomationRule["conditions"];
    actions: AutomationRule["actions"];
    priority?: number;
    stop_processing?: boolean;
  }) => api.post<AutomationRule>("/intelligence/automation-rules/", payload),
  /** Every field optional — a PATCH can flip just `is_active` without
   * resending the whole rule. */
  update: (
    ruleId: string,
    payload: Partial<{
      name: string;
      conditions: AutomationRule["conditions"];
      actions: AutomationRule["actions"];
      priority: number;
      is_active: boolean;
      stop_processing: boolean;
    }>,
  ) => api.patch<AutomationRule>(`/intelligence/automation-rules/${ruleId}/`, payload),
  remove: (ruleId: string) => api.delete<void>(`/intelligence/automation-rules/${ruleId}/`),

  /** Retroactive sweep — the complement to the live post_save pipeline, which
   * only ever reaches a transaction at the moment it's created. */
  applyRules: (payload: { scope?: "uncategorized" | "all"; limit?: number } = {}) =>
    api.post<{ scanned: number; matched: number; effects: number; errors: { transaction_id: string; error: string }[] }>(
      "/intelligence/automation/apply-rules/",
      payload,
    ),
};
