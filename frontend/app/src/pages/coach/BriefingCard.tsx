import { Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import type { Briefing } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { SegmentedControl, Text } from "../../ui";
import { actionRoute } from "./insightMeta";
import { providerLabel } from "./providerLabel";

const PERIODS = [
  { value: "daily" as const, label: "Today" },
  { value: "weekly" as const, label: "This week" },
  { value: "monthly" as const, label: "This month" },
];

function metricNumber(metrics: Record<string, unknown>, key: string): number | null {
  const value = metrics?.[key];
  return typeof value === "number" ? value : null;
}

function metricString(metrics: Record<string, unknown>, key: string): string | null {
  const value = metrics?.[key];
  return typeof value === "string" && value ? value : null;
}

function formatPayday(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return iso;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(
    new Date(year, month - 1, day),
  );
}

function nextActions(metrics: Record<string, unknown>): { title: string; to: string | null; label: string | null }[] {
  const value = metrics?.next_actions;
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const row = item as { title?: unknown; action?: unknown };
      if (typeof row.title !== "string" || !row.title) return null;
      const route =
        row.action && typeof row.action === "object"
          ? actionRoute(row.action as Record<string, unknown>)
          : null;
      return { title: row.title, to: route?.to ?? null, label: route?.label ?? null };
    })
    .filter((row): row is { title: string; to: string | null; label: string | null } => row !== null)
    .slice(0, 3);
}

/**
 * The narrative review — daily, weekly, or monthly.
 *
 * The counts under the summary are deliberate: prose is easy to skim past, and
 * the same figures the narrator wrote from give the reader something concrete
 * to anchor on. `metrics` exists on the API for exactly this reason — the
 * narrative can always be checked against the numbers.
 */
export function BriefingCard({
  briefing,
  period,
  onPeriodChange,
  isLoading,
}: {
  briefing: Briefing | undefined;
  period: "daily" | "weekly" | "monthly";
  onPeriodChange: (p: "daily" | "weekly" | "monthly") => void;
  isLoading?: boolean;
}) {
  const critical = briefing ? metricNumber(briefing.metrics, "critical_count") : null;
  const warnings = briefing ? metricNumber(briefing.metrics, "warning_count") : null;
  const opportunities = briefing ? metricNumber(briefing.metrics, "opportunity_count") : null;
  const savingsRate = briefing ? metricNumber(briefing.metrics, "savings_rate") : null;
  const currency = briefing ? metricString(briefing.metrics, "currency") ?? "USD" : "USD";
  const safeToSpend = briefing ? metricNumber(briefing.metrics, "safe_to_spend_minor") : null;
  const nextPayday = briefing ? metricString(briefing.metrics, "next_payday_on") : null;
  const plan = briefing ? nextActions(briefing.metrics) : [];

  return (
    <section className="lf-briefing" aria-labelledby="briefing-title">
      <header className="lf-briefing-head">
        <p className="lf-briefing-eyebrow">
          <Sparkles size={13} strokeWidth={2} aria-hidden="true" />
          Your briefing
        </p>
        <SegmentedControl
          legend="Briefing period"
          options={PERIODS}
          value={period}
          onChange={onPeriodChange}
        />
      </header>

      {isLoading && !briefing ? (
        <p className="lf-briefing-headline lf-skeleton-text" aria-hidden="true">
          &nbsp;
        </p>
      ) : briefing ? (
        <>
          <h2 className="lf-briefing-headline" id="briefing-title">
            {briefing.headline}
          </h2>
          <p className="lf-briefing-summary">{briefing.summary}</p>

          <dl className="lf-briefing-metrics">
            {critical !== null && critical > 0 && (
              <div data-tone="critical">
                <dt>Needs attention</dt>
                <dd>{critical}</dd>
              </div>
            )}
            {warnings !== null && warnings > 0 && (
              <div data-tone="warning">
                <dt>Worth a look</dt>
                <dd>{warnings}</dd>
              </div>
            )}
            {opportunities !== null && opportunities > 0 && (
              <div data-tone="opportunity">
                <dt>Opportunities</dt>
                <dd>{opportunities}</dd>
              </div>
            )}
            {safeToSpend !== null && (
              <div>
                <dt>Free to spend</dt>
                <dd>{formatAmount(safeToSpend, currency)}</dd>
              </div>
            )}
            {nextPayday && (
              <div>
                <dt>Next payday</dt>
                <dd>{formatPayday(nextPayday)}</dd>
              </div>
            )}
            {savingsRate !== null && (
              <div>
                <dt>Kept from income</dt>
                <dd>{Math.round(savingsRate * 100)}%</dd>
              </div>
            )}
          </dl>

          {plan.length > 0 && (
            <ol className="lf-briefing-plan">
              {plan.map((step, index) => (
                <li key={`${step.title}-${index}`}>
                  {step.to ? (
                    <Link to={step.to}>{step.title}</Link>
                  ) : (
                    <span>{step.title}</span>
                  )}
                </li>
              ))}
            </ol>
          )}

          <Text as="span" tone="tertiary" size="xs">
            {providerLabel(briefing.provider)}
          </Text>
        </>
      ) : (
        <Text tone="tertiary" size="sm">
          No briefing yet — it'll appear once there's enough activity to summarise.
        </Text>
      )}
    </section>
  );
}
