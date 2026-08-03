import type { ReportFilters, ReportPeriod } from "../../api/types";
import { SegmentedControl } from "../../ui";

const PERIODS: { value: ReportPeriod; label: string }[] = [
  { value: "this_month", label: "This month" },
  { value: "last_90_days", label: "90 days" },
  { value: "last_12_months", label: "12 months" },
  { value: "this_year", label: "This year" },
  { value: "all_time", label: "All time" },
];

/**
 * Period selection, shared by every report.
 *
 * One control rather than per-dashboard filters: the filters are the same
 * because the questions are the same shape, and a period picked on one chart
 * applying to all of them is what makes the page feel like a single view
 * rather than fourteen widgets.
 */
export function ReportFilterBar({
  filters,
  onChange,
}: {
  filters: ReportFilters;
  onChange: (next: ReportFilters) => void;
}) {
  return (
    <div className="lf-report-filters">
      <SegmentedControl<ReportPeriod>
        legend="Reporting period"
        options={PERIODS}
        value={(filters.period as ReportPeriod) ?? "last_12_months"}
        onChange={(period) => onChange({ ...filters, period })}
      />
    </div>
  );
}
