import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { coachApi } from "../api/intelligence";
import type { BriefingPeriod, Insight } from "../api/types";
import { useAuth } from "../lib/AuthContext";

const FEED_KEY = "coach-insights";

/** The coach feed. Reads what's stored — generation is a separate action, so
 * opening a page never waits on a recompute. */
export function useInsights(status?: "bookmarked" | "dismissed" | "all") {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [FEED_KEY, activeWorkspace?.tenant.id, status ?? "live"],
    queryFn: () => coachApi.insights(status),
    enabled: !!activeWorkspace,
    staleTime: 60_000,
  });
}

export function useBriefing(period: BriefingPeriod) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["coach-briefing", activeWorkspace?.tenant.id, period],
    queryFn: () => coachApi.briefing(period),
    enabled: !!activeWorkspace,
    // Briefings are generated on read and stored, so they're stable for a
    // while; refetching every focus would rewrite the same prose.
    staleTime: 5 * 60_000,
  });
}

export function useGenerateInsights() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => coachApi.generate(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [FEED_KEY] });
      queryClient.invalidateQueries({ queryKey: ["coach-briefing"] });
    },
  });
}

/**
 * Dismiss, bookmark, or mark an insight acted on.
 *
 * Optimistic: dismissing is the most common action on this surface and it must
 * feel immediate. Waiting for a round-trip before the card leaves the screen
 * makes the feed feel like a form.
 *
 * Rollback restores the exact snapshot on failure — a dismissal that silently
 * fails would have the card reappear on the next refetch with no explanation,
 * which is worse than a slow dismissal.
 */
export function useDecideInsight() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      insightId,
      decision,
    }: {
      insightId: string;
      decision: "dismiss" | "bookmark" | "seen" | "acted";
    }) => coachApi.decide(insightId, decision),

    onMutate: async ({ insightId, decision }) => {
      await queryClient.cancelQueries({ queryKey: [FEED_KEY] });
      const snapshot = queryClient.getQueriesData<Insight[]>({ queryKey: [FEED_KEY] });

      for (const [key, feed] of snapshot) {
        if (!feed) continue;
        queryClient.setQueryData<Insight[]>(
          key,
          decision === "dismiss" || decision === "acted"
            ? // Leaves the live feed entirely.
              feed.filter((i) => i.id !== insightId)
            : // A bookmark keeps it in front of the user — only the badge changes.
              feed.map((i) => (i.id === insightId ? { ...i, status: "bookmarked" } : i)),
        );
      }
      return { snapshot };
    },

    onError: (_err, _vars, context) => {
      for (const [key, feed] of context?.snapshot ?? []) {
        queryClient.setQueryData(key, feed);
      }
    },

    onSettled: () => queryClient.invalidateQueries({ queryKey: [FEED_KEY] }),
  });
}


/** The deployment's AI configuration. Read-only: LLM setup is an environment
 * concern, not a per-workspace one. */
export function useLLMSettings() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["llm-settings", activeWorkspace?.tenant.id],
    queryFn: () => coachApi.llmSettings(),
    enabled: !!activeWorkspace,
    staleTime: 5 * 60_000,
  });
}

/** Toggle this workspace's AI opt-out. Admin-only at the API; the mutation
 * itself doesn't gate on role — a 403 from the server surfaces as an
 * ordinary error the caller can show, rather than the frontend trying to
 * duplicate the backend's authorization logic. */
export function useSetTenantAiEnabled() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) => coachApi.setTenantAiEnabled(enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["llm-settings"] }),
  });
}
