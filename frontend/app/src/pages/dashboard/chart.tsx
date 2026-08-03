import type { CSSProperties } from "react";
import { formatAmount } from "../../lib/money";

interface TooltipPayloadItem {
  name?: string;
  value?: number;
  color?: string;
  dataKey?: string | number;
}

/**
 * Tooltip surface themed with design tokens. Values are plotted in major
 * currency units, so we scale back to minor for `formatAmount`. Pass `currency`
 * via the element (`content={<ChartTooltip currency={cur} />}`); recharts
 * injects `active`/`payload`/`label` when cloning.
 */
export function ChartTooltip({
  active,
  payload,
  label,
  currency,
  labelFormatter,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string | number;
  currency: string;
  labelFormatter?: (label: string | number) => string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="lf-chart-tip">
      {label != null && (
        <div className="lf-chart-tip-label">{labelFormatter ? labelFormatter(label) : String(label)}</div>
      )}
      {payload.map((item, i) => (
        <div className="lf-chart-tip-row" key={i}>
          <span className="lf-chart-tip-dot" style={{ background: item.color } as CSSProperties} />
          {item.name && <span>{item.name}:</span>}
          <strong style={{ color: "var(--lf-text-primary)" }}>
            {formatAmount(Math.round((item.value ?? 0) * 100), currency)}
          </strong>
        </div>
      ))}
    </div>
  );
}
