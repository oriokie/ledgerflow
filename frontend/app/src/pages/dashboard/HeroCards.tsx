import { ChevronDown, Plus, TrendingDown, TrendingUp } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import type { HealthScore, NetWorthByCurrency, NetWorthHistoryPoint } from "../../api/types";
import { useNetWorthBase } from "../../hooks/useFinance";
import { formatAmount, formatAmountSigned, minorToMajor } from "../../lib/money";
import { Badge, Card, Figure, Meter, Text } from "../../ui";
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
      {/* The suffix is a period qualifier ("6 mo"), not part of the figure, so
          it takes the secondary text colour rather than a faded copy of the
          delta's own. Fading it instead put "6 mo" at 4.32:1 — the success
          green has only ~0.8 of headroom over the AA floor, and 0.85 opacity
          spends more than that. */}
      {suffix && <span className="lf-delta-suffix">&nbsp;{suffix}</span>}
    </span>
  );
}

export function NetWorthCard({
  netWorth,
  history,
  currency,
}: {
  netWorth: NetWorthByCurrency | undefined;
  history: NetWorthHistoryPoint[] | undefined;
  currency: string;
}) {
  const { data: consolidated } = useNetWorthBase();
  const points = (history ?? []).map((p) => ({
    label: p.as_of,
    net: minorToMajor(p.net_minor),
  }));

  const delta =
    points.length >= 2 ? percentChange(points[points.length - 1].net, points[0].net) : null;

  if (!netWorth) {
    return (
      <Card eyebrow="Net worth" style={{ gridColumn: "span 2" }}>
        <Text tone="secondary">Welcome to LedgerFlow.</Text>
        <div style={{ marginTop: "var(--lf-space-3)" }}>
          <Link className="lf-btn lf-btn--primary" to="/accounts">
            <Plus size={16} strokeWidth={2} aria-hidden="true" />
            Add your first account
          </Link>
        </div>
      </Card>
    );
  }

  // The card's eyebrow is gone: `Figure` carries the label, and two of them
  // stacked was the page saying "Net worth" twice.
  return (
    <Card style={{ gridColumn: "span 2" }}>
      <Figure
        label="Net worth"
        size="hero"
        amountMinor={netWorth.net_minor}
        currency={currency}
        neutral
        delta={<DeltaChip pct={delta} suffix="6 mo" />}
        hint={
          <>
            {formatAmountSigned(netWorth.assets_minor, currency)} assets &minus;{" "}
            {formatAmountSigned(netWorth.liabilities_minor, currency)} liabilities
          </>
        }
      />

      {consolidated && consolidated.currency_count > 1 && (
        <Text tone="tertiary" size="sm" style={{ marginTop: 2 }}>
          {consolidated.converted ? "\u2248 " : "\u2248 at least "}
          {formatAmount(consolidated.total_minor, consolidated.base_currency)} total across{" "}
          {consolidated.currency_count} currencies
          {!consolidated.converted && " (some rates unavailable)"}
        </Text>
      )}

      {points.length >= 2 && (
        <div className="lf-spark">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="nwSpark" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--lf-iris-600)" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="var(--lf-iris-600)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="label" hide />
              <Tooltip
                content={<ChartTooltip currency={currency} labelFormatter={(l) => formatMonth(l)} />}
                cursor={{ stroke: "var(--lf-border-strong)", strokeWidth: 1 }}
              />
              <Area
                type="monotone"
                dataKey="net"
                name="Net worth"
                stroke="var(--lf-iris-600)"
                strokeWidth={2}
                fill="url(#nwSpark)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

export function HealthCard({ health }: { health: HealthScore | undefined }) {
  const [open, setOpen] = useState(false);

  // A null score means the server measured too little of the picture to state
  // one number. That is the same situation as having no score at all, and it
  // must not be rendered as a figure — the old scorer's habit of filling gaps
  // with flattering defaults is exactly what this replaces.
  if (!health || health.score === null) {
    const missing = (health?.components ?? []).filter((c) => c.score === null);
    return (
      <Card eyebrow="Financial health">
        <Text tone="secondary" size="sm">
          {missing.length > 0
            ? `Not enough data yet to score this. Still needed: ${missing
                .map((c) => c.name.toLowerCase())
                .join(", ")}.`
            : "Not enough data yet — add accounts and a few transactions."}
        </Text>
      </Card>
    );
  }

  const score = health.score;
  const tone = score >= 70 ? "success" : score >= 45 ? "warning" : "danger";

  return (
    <Card>
      {/* Was a hand-styled <p> carrying its colour in an inline style — the
          exact bypass the token lint exists to stop. */}
      <Figure
        label="Financial health"
        size="hero"
        value={Math.round(score)}
        delta={<Badge tone={tone}>{health.band}</Badge>}
      />

      {health.components.length > 0 && (
        <>
          <button
            type="button"
            className="lf-disclosure-toggle"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "Hide breakdown" : "How this is scored"}
            <ChevronDown
              size={14}
              strokeWidth={2}
              aria-hidden="true"
              style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform 150ms" }}
            />
          </button>

          {open && (
            <div className="lf-disclosure-panel">
              {health.components.map((c) =>
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
    </Card>
  );
}

function formatMonth(label: string | number): string {
  const d = new Date(label);
  return Number.isNaN(d.getTime()) ? String(label) : d.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}
