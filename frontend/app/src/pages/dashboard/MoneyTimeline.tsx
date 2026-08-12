import { Link } from "react-router-dom";
import type { Bill, CashflowCalendar } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Illustration } from "../../ui/illustration";

interface TimelineEvent {
  id: string;
  day: string;
  label: string;
  amountMinor: number;
  currency: string;
  kind: "bill" | "inflow" | "outflow" | "risk";
}

function buildTimeline(
  calendar: CashflowCalendar | undefined,
  bills: Bill[] | undefined,
  currency: string,
): TimelineEvent[] {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const horizon = new Date(start);
  horizon.setDate(horizon.getDate() + 14);

  const events: TimelineEvent[] = [];

  for (const b of bills ?? []) {
    if (b.status !== "upcoming" && b.status !== "overdue") continue;
    const due = new Date(b.due_on);
    if (due > horizon) continue;
    events.push({
      id: `bill-${b.id}`,
      day: b.due_on.slice(0, 10),
      label: b.name,
      amountMinor: -Math.abs(b.amount_minor),
      currency: b.currency || currency,
      kind: "bill",
    });
  }

  if (calendar) {
    const days = calendar.days.filter((d) => {
      const day = new Date(d.day);
      return day >= start && day <= horizon;
    });
    for (const d of days) {
      if (d.is_negative) {
        events.push({
          id: `risk-${d.day}`,
          day: d.day,
          label: "Projected shortfall",
          amountMinor: d.closing_minor,
          currency: calendar.currency,
          kind: "risk",
        });
      }
      for (const ev of d.events ?? []) {
        if (!ev.amount_minor) continue;
        // Skip bill-sourced calendar events when we already listed the bill.
        if (ev.bill_id && events.some((e) => e.id === `bill-${ev.bill_id}`)) continue;
        events.push({
          id: `ev-${d.day}-${ev.source}-${ev.amount_minor}-${ev.description}`,
          day: d.day,
          label: ev.description || ev.category_name || "Scheduled",
          amountMinor: ev.amount_minor,
          currency: ev.currency || calendar.currency,
          kind: ev.amount_minor >= 0 ? "inflow" : "outflow",
        });
      }
    }
  }

  const seen = new Set<string>();
  const unique = events.filter((e) => {
    const key = `${e.day}|${e.label}|${e.amountMinor}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  return unique
    .sort((a, b) => a.day.localeCompare(b.day) || Math.abs(b.amountMinor) - Math.abs(a.amountMinor))
    .slice(0, 10);
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

export function MoneyTimeline({
  calendar,
  bills,
  currency,
}: {
  calendar: CashflowCalendar | undefined;
  bills: Bill[] | undefined;
  currency: string;
}) {
  const events = buildTimeline(calendar, bills, currency);

  return (
    <section className="lf-cmd-panel lf-cmd-panel--rail" aria-labelledby="lf-tl-title">
      <header className="lf-cmd-panel-head">
        <h2 id="lf-tl-title">Next 14 days</h2>
        <Link className="lf-section-link" to="/plan?tab=cashflow">
          Calendar
        </Link>
      </header>

      {events.length === 0 ? (
        <div className="lf-cmd-quiet lf-cmd-quiet--compact">
          <Illustration name="cycle" size="spot" />
          <p>No scheduled money movements in the next two weeks.</p>
        </div>
      ) : (
        <ol className="lf-tl-list">
          {events.map((e) => (
            <li key={e.id} className="lf-tl-item" data-kind={e.kind}>
              <time className="lf-tl-day" dateTime={e.day}>
                {dayLabel(e.day)}
              </time>
              <div className="lf-tl-main">
                <span className="lf-tl-label">{e.label}</span>
                <span className="lf-tl-amt" data-kind={e.kind}>
                  {formatAmount(Math.abs(e.amountMinor), e.currency)}
                  {e.kind === "inflow" ? " in" : e.kind === "risk" ? "" : " out"}
                </span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
