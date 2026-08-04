// Existing analytics widgets, used by AnalyticsPage.
export { CashFlowChart } from "./CashFlowChart";
export { FinancialIndependencePanel } from "./FinancialIndependencePanel";
export { CashflowStatement } from "./CashflowStatement";
export { CategoryBreakdown } from "./CategoryBreakdown";
export { CategoryDrilldown } from "./CategoryDrilldown";
export { ComparisonCards } from "./ComparisonCards";
export { DeltaBadge } from "./DeltaBadge";

// Reporting platform: one renderer driving all fourteen dashboards.
export { ReportCard } from "./ReportCard";
export { ReportFilterBar } from "./ReportFilterBar";
export {
  CHART_COLORS,
  caveatsOf,
  formatTimeLabel,
  humanizeKey,
  isMoneyKey,
  numericKeys,
  timeKeyOf,
} from "./reportRenderers";
