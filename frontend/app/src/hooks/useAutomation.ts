import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { automationApi } from "../api/automation";
import { useAuth } from "../lib/AuthContext";

const KEY = "automation-queue";

export function useAutomationQueue(kind?: string) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [KEY, activeWorkspace?.tenant.id, kind ?? "all"],
    queryFn: () => automationApi.queue(kind),
    enabled: !!activeWorkspace,
  });
}

export function useScan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (days?: number) => automationApi.scan(days),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

/**
 * Decide one suggestion.
 *
 * Optimistic: reviewing a backlog is a rhythm, and a round-trip between each
 * tap breaks it. Rollback restores the exact snapshot, because a silently
 * failed decision would have the card reappear later with no explanation.
 */
export function useDecideSuggestion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "approve" | "reject" }) =>
      automationApi.decide(id, decision),
    onMutate: async ({ id }) => {
      await queryClient.cancelQueries({ queryKey: [KEY] });
      const snapshot = queryClient.getQueriesData({ queryKey: [KEY] });
      for (const [key, data] of snapshot) {
        const queue = data as { suggestions?: { id: string }[]; pending?: number } | undefined;
        if (!queue?.suggestions) continue;
        queryClient.setQueryData(key, {
          ...queue,
          suggestions: queue.suggestions.filter((s) => s.id !== id),
          pending: Math.max(0, (queue.pending ?? 1) - 1),
        });
      }
      return { snapshot };
    },
    onError: (_e, _v, context) => {
      for (const [key, data] of context?.snapshot ?? []) queryClient.setQueryData(key, data);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function useBulkDecide() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, decision }: { ids: string[]; decision: "approve" | "reject" }) =>
      automationApi.bulkDecide(ids, decision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [KEY] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
    },
  });
}
