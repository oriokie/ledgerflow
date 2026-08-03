import { api } from "./client";
import type { Budget, BudgetStatus } from "./types";

export const budgetingApi = {
  listBudgets: () => api.get<Budget[]>("/budgeting/budgets/"),
  createBudget: (payload: { name: string; currency: string; starts_on: string; period?: string }) =>
    api.post<Budget>("/budgeting/budgets/", payload),

  addBudgetLine: (budgetId: string, payload: { category_id: string; limit_minor: number; rollover?: boolean }) =>
    api.post(`/budgeting/budgets/${budgetId}/lines/`, payload),

  updateBudgetLine: (
    budgetId: string,
    lineId: string,
    payload: { limit_minor?: number; rollover?: boolean },
  ) => api.patch(`/budgeting/budgets/${budgetId}/lines/${lineId}/`, payload),

  removeBudgetLine: (budgetId: string, lineId: string) =>
    api.delete(`/budgeting/budgets/${budgetId}/lines/${lineId}/`),

  deleteBudget: (budgetId: string) => api.delete(`/budgeting/budgets/${budgetId}/`),

  budgetStatus: (budgetId: string, asOf?: string) =>
    api.get<BudgetStatus>(`/budgeting/budgets/${budgetId}/status/${asOf ? `?as_of=${asOf}` : ""}`),
};
