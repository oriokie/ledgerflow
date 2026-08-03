import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { budgetingApi } from "../api/budgeting";
import { useAuth } from "../lib/AuthContext";

export function useBudgets() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["budgets", activeWorkspace?.tenant.id],
    queryFn: () => budgetingApi.listBudgets(),
    enabled: !!activeWorkspace,
  });
}

export function useCreateBudget() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: budgetingApi.createBudget,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["budgets"] }),
  });
}

export function useAddBudgetLine() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      budgetId,
      payload,
    }: {
      budgetId: string;
      payload: { category_id: string; limit_minor: number; rollover?: boolean };
    }) => budgetingApi.addBudgetLine(budgetId, payload),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["budget-status", variables.budgetId] });
    },
  });
}

export function useUpdateBudgetLine() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      budgetId,
      lineId,
      payload,
    }: {
      budgetId: string;
      lineId: string;
      payload: { limit_minor?: number; rollover?: boolean };
    }) => budgetingApi.updateBudgetLine(budgetId, lineId, payload),
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({ queryKey: ["budget-status", variables.budgetId] }),
  });
}

export function useRemoveBudgetLine() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ budgetId, lineId }: { budgetId: string; lineId: string }) =>
      budgetingApi.removeBudgetLine(budgetId, lineId),
    onSuccess: (_data, variables) =>
      queryClient.invalidateQueries({ queryKey: ["budget-status", variables.budgetId] }),
  });
}

export function useDeleteBudget() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (budgetId: string) => budgetingApi.deleteBudget(budgetId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["budgets"] }),
  });
}

export function useBudgetStatus(budgetId: string | undefined, asOf?: string) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["budget-status", budgetId, asOf],
    queryFn: () => budgetingApi.budgetStatus(budgetId!, asOf),
    enabled: !!activeWorkspace && !!budgetId,
  });
}
