import { api } from "./client";
import type { FIProjection, ReportFilters, ReportMeta, ReportResult } from "./types";

function toQuery(filters: ReportFilters = {}): string {
  const q = new URLSearchParams();
  if (filters.period) q.set("period", filters.period);
  if (filters.start) q.set("start", filters.start);
  if (filters.end) q.set("end", filters.end);
  if (filters.currency) q.set("currency", filters.currency);
  if (filters.compare_previous) q.set("compare_previous", "true");
  // Repeated keys rather than a joined string: DRF's ListField reads them that
  // way, and a comma-joined UUID list would arrive as one malformed value.
  for (const id of filters.account_ids ?? []) q.append("account_ids", id);
  for (const id of filters.category_ids ?? []) q.append("category_ids", id);
  return q.toString();
}

export const reportsApi = {
  /** What reports exist and how each wants to be drawn. */
  catalog: () => api.get<ReportMeta[]>("/analytics/reports/"),

  /** Null when the report has nothing to show — the API answers 204 rather
   * than a shape full of zeroes. */
  run: (slug: string, filters: ReportFilters = {}) =>
    api.get<ReportResult | null>(`/analytics/reports/${slug}/?${toQuery(filters)}`),

  /** API path for the CSV export — fetched with auth headers, not linked. */
  exportPath: (slug: string, filters: ReportFilters = {}) =>
    `/analytics/reports/${slug}/export/?${toQuery(filters)}`,
};

export const fiApi = {
  /** 404 with an explanation when history is too thin — surfaced as copy, not an error state. */
  projection: () => api.get<FIProjection>("/analytics/financial-independence/"),
};
