import type { ActivityEvent } from "../../api/household";
import { EyeOff, History } from "lucide-react";
import { Card, EmptyState, Text } from "../../ui";

function when(iso: string): string {
  const then = new Date(iso);
  const mins = Math.round((Date.now() - then.getTime()) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
  if (mins < 10080) return `${Math.round(mins / 1440)}d ago`;
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/**
 * The household's activity, most recent first.
 *
 * Private events appear here with their specifics already omitted by the
 * server. Their existence is not the secret — a timeline with silent gaps is
 * itself informative, and worse than one that says plainly that something
 * happened on an account you cannot see.
 */
export function ActivityCard({ events }: { events: ActivityEvent[] }) {
  return (
    <Card title="What's been happening" accent="save">
      {events.length === 0 ? (
        <EmptyState
          icon={History}
          title="Nothing yet"
          body="Every change either of you makes lands here — budgets, goals, bills, approvals, settings. Nothing happens silently."
        />
      ) : (
        <ol className="lf-timeline">
          {events.map((e) => (
            <li key={e.id} className="lf-timeline-item">
              <span className="lf-timeline-dot" aria-hidden="true" />
              <div>
                <Text size="sm">
                  {e.summary}
                  {e.is_private && (
                    <span className="lf-timeline-private" title="Details are private">
                      {" "}
                      <EyeOff size={12} strokeWidth={1.8} aria-hidden="true" />
                    </span>
                  )}
                </Text>
                <Text tone="tertiary" size="xs">
                  {e.actor} · {when(e.occurred_at)}
                </Text>
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
