import { ChevronDown, TrendingDown, TrendingUp } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import type {
  CashflowCalendar,
  HealthScore,
  NetWorthBase,
  NetWorthByCurrency,
  NetWorthHistoryPoint,
} from "../../api/types";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import { formatAmount, formatAmountSigned, minorToMajor } from "../../lib/money";
import { Badge, Meter, Text } from "../../ui";
import { ChartTooltip } from "./chart";
import { formatDelta, percentChange } from "./metrics";

function DeltaChip({ pct, suffix }: { pct: number | null; suffix?: string }) {
  if (pct == null) return null;
  const dir = pct > 0.05 ? "up" : pct < -0.05 ? "down" : "flat";
  const Icon = dir === "down" ? TrendingDown : TrendingUp;
  return (
    <span className="lf-delta" data-tone={dir === "up" ? "good" : dir === "down" ? "bad" : undefined}>
      {dir !== "flat" && <Icon size={12} strokeWidth={2.2} aria-hidden="true" />}
      {formatDelta(pct)}
      {suffix && <span className="lf-delta-suffix">&nbsp;{suffix}</span>}
    </span>
  );
}

export function FinancialPulse({
  netWorth,
  history,
  consolidated,
  health,
  calendar,
  currency,
  aiEnabled,
}: {
  netWorth: NetWorthByCurrency | undefined;
  history: NetWorthHistoryPoint[] | undefined;
  consolidated: NetWorthBase | undefined;
  health: HealthScore | undefined;
  calendar: CashflowCalendar | undefined;
  currency: string;
  aiEnabled: boolean;
}) {
  const [healthOpen, setHealthOpen] = useState(false);
  const animate = !usePrefersReducedMotion();
  const points = (history ?? []).map((p) => ({
    label: p.as_of,
    net: minorToMajor(p.net_minor),
  }));
  const delta =
    points.length >= 2 ? percentChange(points[points.length - 1].net, points[0].net) : null;

  if (!netWorth) {
    return (
      <section className="lf-pulse" aria-labelledby="lf-pulse-title">
        <div className="lf-pulse-empty">
          <h2 id="lf-pulse-title" className="lf-pulse-kicker">
            Financial pulse
          </h2>
          <Text tone="secondary">Add an account to see net worth and health here.</Text>
          <Link className="lf-btn lf-btn--primary" to="/accounts">
            Add account
          </Link>
        </div>
      </section>
    );
  }

  const score = health?.score ?? null;
  const healthTone =
    score == null ? null : score >= 70 ? "success" : score >= 45 ? "warning" : "danger";

  return (
    <section className="lf-pulse lf-cmd-enter" aria-labelledby="lf-pulse-title">
      <div className="lf-pulse-main">
        <p className="lf-pulse-kicker" id="lf-pulse-title">
          Financial pulse
        </p>
        <p className="lf-pulse-label">Net worth</p>
        <p className="lf-pulse-figure">
          <span className="lf-amount" data-neutral="">
            {formatAmount(netWorth.net_minor, currency)}
          </span>
        </p>
        <div className="lf-pulse-meta">
          <DeltaChip pct={delta} suffix="6 mo" />
          <span className="lf-pulse-split">
            {formatAmount(netWorth.assets_minor, currency)} assets −{" "}
            {formatAmount(netWorth.liabilities_minor, currency)} liabilities
          </span>
        </div>

        {consolidated && consolidated.currency_count > 1 && (
          <Text tone="tertiary" size="sm" style={{ marginTop: 4 }}>
            {consolidated.converted ? "≈ " : "≈ at least "}
            {formatAmount(consolidated.total_minor, consolidated.base_currency)} across{" "}
            {consolidated.currency_count} currencies
            {!consolidated.converted && " (some rates unavailable)"}
          </Text>
        )}

        {points.length >= 2 && (
          <div className="lf-pulse-spark" aria-hidden={false}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="pulseSpark" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--lf-action-primary)" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="var(--lf-action-primary)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="label" hide />
                <Tooltip
                  content={
                    <ChartTooltip
                      currency={currency}
                      labelFormatter={(l) =>
                        new Date(l).toLocaleDateString(undefined, { month: "short", year: "numeric" })
                      }
                    />
                  }
                  cursor={{ stroke: "var(--lf-border-strong)", strokeWidth: 1 }}
                />
                <Area
                  type="monotone"
                  dataKey="net"
                  name="Net worth"
                  stroke="var(--lf-action-primary)"
                  strokeWidth={2.25}
                  fill="url(#pulseSpark)"
                  isAnimationActive={animate}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="lf-pulse-side">
        {aiEnabled && (
          <div className="lf-pulse-health">
            <p className="lf-pulse-side-label">Health</p>
            {score == null ? (
              <Text tone="secondary" size="sm">
                {(health?.components ?? []).some((c) => c.score === null)
                  ? "Not enough coverage to score yet."
                  : "Not enough data yet to score health."}
              </Text>
            ) : (
              <>
                <div className="lf-pulse-health-row">
                  <span className="lf-pulse-health-score">{Math.round(score)}</span>
                  {healthTone && <Badge tone={healthTone}>{health!.band}</Badge>}
                </div>
                {health!.components.length > 0 && (
                  <>
                    <button
                      type="button"
                      className="lf-disclosure-toggle"
                      aria-expanded={healthOpen}
                      onClick={() => setHealthOpen((v) => !v)}
                    >
                      {healthOpen ? "Hide breakdown" : "How this is scored"}
                      <ChevronDown
                        size={14}
                        strokeWidth={2}
                        aria-hidden="true"
                        style={{
                          transform: healthOpen ? "rotate(180deg)" : "none",
                          transition: "transform 150ms",
                        }}
                      />
                    </button>
                    {healthOpen && (
                      <div className="lf-disclosure-panel">
                        {health!.components.map((c) =>
                          c.score === null ? (
                            <Text key={c.name} tone="tertiary" size="sm">
                              {c.name} — {c.detail}
                            </Text>
                          ) : (
                            <Meter
                              key={c.name}
                              value={c.score}
                              label={c.name}
                              caption={`${Math.round(c.score)}`}
                            />
                          ),
                        )}
                      </div>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        )}

        {calendar && (
          <div className="lf-pulse-sts">
            <p className="lf-pulse-side-label">Safe to spend</p>
            <p className="lf-pulse-sts-figure lf-amount" data-certainty="projected">
              {formatAmount(calendar.safe_to_spend_minor, calendar.currency)}
            </p>
            <Text tone="secondary" size="sm">
              {calendar.safe_to_spend_minor > 0 ? (
                <>
                  Beyond scheduled bills
                  {calendar.safe_to_spend_basis === "everyday" ? " and usual habits" : ""}.
                </>
              ) : (
                <>
                  Balance may dip to{" "}
                  {formatAmountSigned(calendar.lowest_balance_minor, calendar.currency)}
                  {calendar.lowest_balance_on
                    ? ` around ${new Date(calendar.lowest_balance_on).toLocaleDateString(undefined, {
                        day: "numeric",
                        month: "short",
                      })}`
                    : ""}
                  .
                </>
              )}{" "}
              <Link className="lf-link" to="/plan?tab=cashflow">
                Projection
              </Link>
            </Text>
          </div>
        )}
      </div>
    </section>
  );
}
