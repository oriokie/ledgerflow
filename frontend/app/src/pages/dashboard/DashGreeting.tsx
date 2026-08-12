import { SegmentedControl } from "../../ui";
import type { PeriodKey } from "./metrics";

const PERIOD_OPTIONS: { value: PeriodKey; label: string }[] = [
  { value: "this-month", label: "This month" },
  { value: "last-month", label: "Last month" },
  { value: "last-30d", label: "30 days" },
  { value: "ytd", label: "Year" },
];

export function DashGreeting({
  hello,
  firstName,
  statement,
  period,
  onPeriodChange,
  rangeLabel,
}: {
  hello: string;
  firstName?: string;
  statement: string | null;
  period: PeriodKey;
  onPeriodChange: (p: PeriodKey) => void;
  rangeLabel: string;
}) {
  return (
    <header className="lf-cmd-greet">
      <div className="lf-cmd-greet-copy">
        <p className="lf-cmd-eyebrow">Command center</p>
        <h1 className="lf-cmd-title">
          {hello}
          {firstName ? `, ${firstName}` : ""}
        </h1>
        <p className="lf-cmd-statement">
          {statement ?? `Your money overview · ${rangeLabel}`}
        </p>
      </div>
      <div className="lf-cmd-greet-controls">
        <SegmentedControl<PeriodKey>
          legend="Time period"
          value={period}
          onChange={onPeriodChange}
          options={PERIOD_OPTIONS}
        />
      </div>
    </header>
  );
}
