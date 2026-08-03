import { api } from "./client";
import type { AutomationQueue, AutomationSuggestion } from "./types";

export const automationApi = {
  /** Idempotent: a finding already decided is left alone, so rescanning never
   * resurrects something dismissed. */
  scan: (days = 120) => api.post<{ created: number; refreshed: number; auto_applied: number }>(
    "/intelligence/automation/scan/",
    { days },
  ),

  queue: (kind?: string) =>
    api.get<AutomationQueue>(`/intelligence/automation/queue/${kind ? `?kind=${kind}` : ""}`),

  decide: (suggestionId: string, decision: "approve" | "reject") =>
    api.post<AutomationSuggestion>(`/intelligence/automation/${suggestionId}/${decision}/`, {}),

  bulkDecide: (suggestionIds: string[], decision: "approve" | "reject") =>
    api.post<{ decided: number; requested: number }>("/intelligence/automation/bulk/", {
      suggestion_ids: suggestionIds,
      decision,
    }),
};
