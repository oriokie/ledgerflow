import { useQuery } from "@tanstack/react-query";
import { reportsApi } from "../api/reports";
import type { ReportFilters } from "../api/types";
import { useAuth } from "../lib/AuthContext";

const PREFIX = "reports";

/** The catalogue changes only on deploy, so it is cached hard. */
export function useReportCatalog() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "catalog", activeWorkspace?.tenant.id],
    queryFn: () => reportsApi.catalog(),
    enabled: !!activeWorkspace,
    staleTime: 60 * 60_000,
  });
}

/**
 * Run one report.
 *
 * `placeholderData` holds the previous result while filters change, so the
 * dashboard doesn't blank out between periods — the charts animate to the new
 * data instead of disappearing and reappearing.
 */
export function useReport(slug: string, filters: ReportFilters, enabled = true) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, slug, activeWorkspace?.tenant.id, filters],
    queryFn: () => reportsApi.run(slug, filters),
    enabled: !!activeWorkspace && enabled,
    placeholderData: (previous) => previous,
    staleTime: 60_000,
  });
}
