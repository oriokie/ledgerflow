import { BarChart3 } from "lucide-react";
import { useMemo, useState } from "react";
import { reportsApi } from "../api/reports";
import type { ReportFilters, ReportGroup, ReportMeta } from "../api/types";
import { useReport, useReportCatalog } from "../hooks/useReports";
import { Link } from "react-router-dom";
import { Card, EmptyState, Grid, Inline, PageHeader, SegmentedControl, SkeletonCard } from "../ui";
import { FinancialIndependencePanel, ReportCard, ReportFilterBar } from "./analytics";

const GROUPS: { value: ReportGroup; label: string }[] = [
  { value: "position", label: "Where you stand" },
  { value: "flow", label: "Money in and out" },
  { value: "spending", label: "Where it goes" },
  { value: "compare", label: "Compared" },
];

/** One report, fetched independently so a slow one never blocks the rest. */
function Report({ meta, filters }: { meta: ReportMeta; filters: ReportFilters }) {
  const { data, isLoading } = useReport(meta.slug, filters);
  if (isLoading && !data) return <SkeletonCard />;
  return (
    <ReportCard
      meta={meta}
      result={data}
      exportPath={reportsApi.exportPath(meta.slug, filters)}
    />
  );
}

/**
 * The reporting platform.
 *
 * Reports are grouped by the question they answer rather than listed
 * alphabetically — fourteen charts on one screen is a wall, four tabs of three
 * or four is a tool. The grouping comes from the backend catalogue, so adding
 * a report places itself.
 *
 * Each report fetches independently. One heavy query then delays only its own
 * card instead of holding the whole page.
 */
/** `embedded` renders this page as a tab panel inside a hub (`/plan`,
 * `/insights`). The hub owns the <h1>, so the page must not render its own
 * PageHeader — two page titles on one route is a broken heading outline.
 * The period filter and the review link are not part of that title, though,
 * so they still render when embedded — just in a plain row instead of a
 * full PageHeader. */
export function ReportsPage({ embedded }: { embedded?: boolean } = {}) {
  const [group, setGroup] = useState<ReportGroup>("position");
  const [filters, setFilters] = useState<ReportFilters>({ period: "last_12_months" });

  const { data: catalog, isLoading } = useReportCatalog();

  const visible = useMemo(
    () => (catalog ?? []).filter((report) => report.group === group),
    [catalog, group],
  );

  const actions = (
    <Inline gap={2}>
      <Link className="lf-section-link" to="/review">
        Financial review
      </Link>
      <ReportFilterBar filters={filters} onChange={setFilters} />
    </Inline>
  );

  return (
    <>
      {embedded ? (
        <div className="lf-page-header-actions" style={{ justifyContent: "flex-end", marginBottom: "var(--lf-space-4)" }}>
          {actions}
        </div>
      ) : (
        <PageHeader
          eyebrow="Meaning"
          title="Reports"
          description="Fourteen views of your money. Pick a period once and it applies to all of them."
          illustration="insight"
          actions={actions}
        />
      )}

      {/* The advisor question, pinned above the catalog when looking at
          position: reports describe where money went; this one says where the
          person is going. */}
      {group === "position" && (
        <div className="lf-dash-section">
          <FinancialIndependencePanel />
        </div>
      )}

      <div className="lf-report-groups">
        <SegmentedControl<ReportGroup>
          legend="Report group"
          options={GROUPS}
          value={group}
          onChange={setGroup}
        />
      </div>

      {isLoading && <SkeletonCard />}

      {!isLoading && (catalog?.length ?? 0) === 0 && (
        <Card>
          <EmptyState
            icon={BarChart3}
            illustration="search"
            title="No reports available"
            body="Reports appear once there's activity to summarise."
          />
        </Card>
      )}

      <Grid cols={2} gap={4}>
        {visible.map((meta) => (
          <Report key={meta.slug} meta={meta} filters={filters} />
        ))}
      </Grid>
    </>
  );
}
