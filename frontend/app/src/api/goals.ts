import { api } from "./client";
import type {
  GoalContribution,
  GoalForecast,
  GoalKind,
  GoalPriority,
  GoalRecommendation,
  SavingsGoal,
} from "./types";

export const goalsApi = {
  listGoals: (includeArchived = false) =>
    api.get<SavingsGoal[]>(`/goals/goals/${includeArchived ? "?include_archived=true" : ""}`),

  listContributions: (goalId: string) =>
    api.get<GoalContribution[]>(`/goals/goals/${goalId}/contributions/`),

  createGoal: (payload: {
    name: string;
    kind?: GoalKind;
    currency: string;
    target_minor: number;
    target_date?: string;
    /** Omit to let the server derive it from `kind`. */
    priority?: GoalPriority;
    planned_monthly_minor?: number;
    tracking?: "manual" | "account_balance";
    linked_account_id?: string;
    notes?: string;
  }) => api.post<SavingsGoal>("/goals/goals/", payload),

  archiveGoal: (goalId: string) => api.delete<void>(`/goals/goals/${goalId}/`),

  updateGoal: (
    goalId: string,
    payload: {
      name?: string;
      kind?: GoalKind;
      target_minor?: number;
      target_date?: string | null;
      priority?: GoalPriority;
      planned_monthly_minor?: number | null;
      status?: string;
      notes?: string;
    },
  ) => api.patch<SavingsGoal>(`/goals/goals/${goalId}/`, payload),

  /** Full forecast for one goal, including the projection series for charts. */
  goalForecast: (goalId: string) => api.get<GoalForecast>(`/goals/goals/${goalId}/forecast/`),

  /** Forecasts for every live goal, in funding order. */
  forecasts: () => api.get<GoalForecast[]>("/goals/goals/forecast/"),

  /** Suggestions derived from the workspace's own figures. May be empty. */
  recommendations: () => api.get<GoalRecommendation[]>("/goals/goals/recommendations/"),

  setAutoContribution: (
    goalId: string,
    payload: { enabled: boolean; amount_minor?: number | null; day_of_month?: number | null },
  ) => api.put<SavingsGoal>(`/goals/goals/${goalId}/auto-contribution/`, payload),

  /**
   * Log a contribution.
   *
   * Omitting `fromAccountId` records money the user has already set aside —
   * nothing moves, which is the historical behaviour and still the default.
   * Supplying it posts a real transfer out of that account into the goal's
   * destination, so the source balance genuinely drops.
   */
  contribute: (
    goalId: string,
    amountMinor: number,
    memo?: string,
    fromAccountId?: string,
    toAccountId?: string,
  ) =>
    api.post<{
      id: string;
      goal_id: string;
      amount_minor: number;
      funded: boolean;
      goal: SavingsGoal;
    }>(`/goals/goals/${goalId}/contributions/`, {
      amount_minor: amountMinor,
      memo,
      from_account_id: fromAccountId ?? null,
      to_account_id: toAccountId ?? null,
    }),
};
