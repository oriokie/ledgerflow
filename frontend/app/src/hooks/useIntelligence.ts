import { useQuery } from "@tanstack/react-query";
import { intelligenceApi } from "../api/intelligence";
import { useAuth } from "../lib/AuthContext";

export function useHealthScore(enabled = true) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["health-score", activeWorkspace?.tenant.id],
    queryFn: () => intelligenceApi.healthScore(),
    enabled: !!activeWorkspace && enabled,
  });
}

export function useRecommendations(enabled = true) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["recommendations", activeWorkspace?.tenant.id],
    queryFn: () => intelligenceApi.recommendations(),
    enabled: !!activeWorkspace && enabled,
  });
}

export function useAnomalies(enabled = true) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["anomalies", activeWorkspace?.tenant.id],
    queryFn: () => intelligenceApi.anomalies(),
    enabled: !!activeWorkspace && enabled,
  });
}

export function useForecast(enabled = true) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["forecast", activeWorkspace?.tenant.id],
    queryFn: () => intelligenceApi.forecast(),
    enabled: !!activeWorkspace && enabled,
  });
}

/** Dated achievements. Cheap and stable — a milestone that has happened does
 * not un-happen, so this can sit on a long stale time. */
/** Interpret a typed question as a ledger filter.
 *
 * `enabled` is the whole cost control: this only fires for text that reads like
 * a question, after the same debounce as the record search. */
export function useAsk(question: string, enabled: boolean) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["ask", activeWorkspace?.tenant.id, question],
    queryFn: () => intelligenceApi.ask(question),
    enabled: !!activeWorkspace && enabled && question.length >= 8,
    staleTime: 60_000,
  });
}

export function useMilestones() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["milestones", activeWorkspace?.tenant.id],
    queryFn: () => intelligenceApi.milestones(),
    enabled: !!activeWorkspace,
    staleTime: 5 * 60_000,
  });
}

export function useNetWorthHistory(months = 12) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["net-worth-history", activeWorkspace?.tenant.id, months],
    queryFn: () => intelligenceApi.netWorthHistory(months),
    enabled: !!activeWorkspace,
  });
}

export function useSpendingTrend(months = 6) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["spending-trend", activeWorkspace?.tenant.id, months],
    queryFn: () => intelligenceApi.spendingTrend(months),
    enabled: !!activeWorkspace,
  });
}

// ---------------------------------------------------------------- extended
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { automationApi, suggestionsApi } from "../api/intelligence";

export function useSuggestions(status = "pending", enabled = true) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["suggestions", activeWorkspace?.tenant.id, status],
    queryFn: () => suggestionsApi.list(status),
    enabled: !!activeWorkspace && enabled,
  });
}

export function useDecideSuggestion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "accept" | "reject" }) =>
      suggestionsApi.decide(id, decision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["suggestions"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
    },
  });
}

export function useAutomationRules() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["automation-rules", activeWorkspace?.tenant.id],
    queryFn: () => automationApi.list(),
    enabled: !!activeWorkspace,
  });
}

export function useCreateAutomationRule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: automationApi.create,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["automation-rules"] }),
  });
}

export function useDeleteAutomationRule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: automationApi.remove,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["automation-rules"] }),
  });
}

export function useCashRunway(enabled = true) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["cash-runway", activeWorkspace?.tenant.id],
    queryFn: () => intelligenceApi.cashRunway(),
    enabled: !!activeWorkspace && enabled,
  });
}
