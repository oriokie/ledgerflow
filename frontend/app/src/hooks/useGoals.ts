import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { goalsApi } from "../api/goals";
import { useAuth } from "../lib/AuthContext";

export function useGoals(includeArchived = false) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["goals", activeWorkspace?.tenant.id, includeArchived],
    queryFn: () => goalsApi.listGoals(includeArchived),
    enabled: !!activeWorkspace,
  });
}

export function useCreateGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: goalsApi.createGoal,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["goals"] }),
  });
}

/** Forecasts for all live goals. Separate from useGoals so a card can show
 * progress immediately while the forecast (which reads contribution history)
 * resolves behind it. */
export function useGoalForecasts() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["goal-forecasts", activeWorkspace?.tenant.id],
    queryFn: () => goalsApi.forecasts(),
    enabled: !!activeWorkspace,
  });
}

export function useGoalForecast(goalId: string | undefined) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["goal-forecast", goalId],
    queryFn: () => goalsApi.goalForecast(goalId!),
    enabled: !!activeWorkspace && !!goalId,
  });
}

export function useGoalRecommendations() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["goal-recommendations", activeWorkspace?.tenant.id],
    queryFn: () => goalsApi.recommendations(),
    enabled: !!activeWorkspace,
  });
}

export function useUpdateGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ goalId, payload }: { goalId: string; payload: Parameters<typeof goalsApi.updateGoal>[1] }) =>
      goalsApi.updateGoal(goalId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["goals"] });
      queryClient.invalidateQueries({ queryKey: ["goal-forecasts"] });
    },
  });
}

export function useSetAutoContribution() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      goalId,
      payload,
    }: {
      goalId: string;
      payload: Parameters<typeof goalsApi.setAutoContribution>[1];
    }) => goalsApi.setAutoContribution(goalId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["goals"] }),
  });
}

export function useArchiveGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: goalsApi.archiveGoal,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["goals"] }),
  });
}

export function useGoalContributions(goalId: string | undefined) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["goal-contributions", goalId],
    queryFn: () => goalsApi.listContributions(goalId!),
    enabled: !!activeWorkspace && !!goalId,
  });
}

export function useContributeToGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      goalId,
      amountMinor,
      memo,
      fromAccountId,
      toAccountId,
    }: {
      goalId: string;
      amountMinor: number;
      memo?: string;
      /** Fund the contribution by transferring out of this account. */
      fromAccountId?: string;
      toAccountId?: string;
    }) => goalsApi.contribute(goalId, amountMinor, memo, fromAccountId, toAccountId),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["goals"] });
      queryClient.invalidateQueries({ queryKey: ["goal-contributions", variables.goalId] });
      // A funded contribution moved real money, so anything reading a balance
      // is now stale. Scoped to the funded case: an unfunded contribution
      // changes no balance, and refetching the world for it would be noise.
      if (variables.fromAccountId) {
        queryClient.invalidateQueries({ queryKey: ["accounts"] });
        queryClient.invalidateQueries({ queryKey: ["net-worth"] });
        queryClient.invalidateQueries({ queryKey: ["transactions"] });
        queryClient.invalidateQueries({ queryKey: ["cashflow-calendar"] });
      }
    },
  });
}
