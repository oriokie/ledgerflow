import { useEffect, useMemo, useState } from "react";
import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications } from "../hooks/useNotifications";
import { formatDateLong } from "../lib/money";
import { api, ApiError } from "../api/client";
import type { Notification, Paginated } from "../api/types";
import { BellOff } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Grid,
  Inline,
  LoadingBlock,
  PageHeader,
  SegmentedControl,
  Text,
  useToast,
} from "../ui";

const SEVERITY_TONE: Record<string, "neutral" | "warning" | "danger"> = {
  info: "neutral",
  warning: "warning",
  critical: "danger",
};

type SeverityFilter = "all" | Notification["severity"];

const SEVERITY_OPTIONS: { value: SeverityFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "info", label: "Info" },
  { value: "warning", label: "Warning" },
  { value: "critical", label: "Critical" },
];

/** Pull the opaque `cursor` param out of a full `next` URL. The API returns
 * an absolute-ish URL (see CursorPagination); callers only ever need the
 * token to ask for the next page. */
function extractCursor(nextUrl: string | null): string | null {
  if (!nextUrl) return null;
  try {
    return new URL(nextUrl, window.location.origin).searchParams.get("cursor");
  } catch {
    return null;
  }
}

export function NotificationsPage() {
  const { data, isLoading } = useNotifications(false);
  const markRead = useMarkNotificationRead();
  const markAllRead = useMarkAllNotificationsRead();
  const toast = useToast();

  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>("all");

  // Pages fetched beyond the first, via "Load more". Reset whenever the base
  // page changes (a genuinely new first page — structural sharing keeps the
  // same `data` reference across no-op polls, so this doesn't fire every
  // 60s) so the cursor chain always starts from what's actually on screen.
  const [morePages, setMorePages] = useState<Notification[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    setMorePages([]);
    setNextCursor(extractCursor(data?.next ?? null));
  }, [data]);

  const allResults = useMemo(() => [...(data?.results ?? []), ...morePages], [data, morePages]);
  const filteredResults = useMemo(
    () => (severityFilter === "all" ? allResults : allResults.filter((n) => n.severity === severityFilter)),
    [allResults, severityFilter],
  );

  const loadMore = async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const params = new URLSearchParams({ cursor: nextCursor });
      const page = await api.get<Paginated<Notification> & { unread_count: number }>(
        `/notifications/?${params.toString()}`,
      );
      setMorePages((prev) => [...prev, ...page.results]);
      setNextCursor(extractCursor(page.next));
    } catch (err) {
      toast(err instanceof ApiError ? err.detail : "Couldn't load more notifications.");
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow={`${data?.unread_count ?? 0} unread`}
        title="Notifications"
        actions={
          <Button
            variant="ghost"
            onClick={() => markAllRead.mutate()}
            disabled={markAllRead.isPending || !data?.unread_count}
          >
            Mark all read
          </Button>
        }
      />

      {!isLoading && allResults.length > 0 && (
        <Inline gap={2} style={{ marginBottom: "var(--lf-space-4)" }}>
          <SegmentedControl
            legend="Filter by severity"
            value={severityFilter}
            onChange={setSeverityFilter}
            options={SEVERITY_OPTIONS}
          />
        </Inline>
      )}

      {isLoading && <LoadingBlock />}
      {!isLoading && allResults.length === 0 && (
        <Card>
          <EmptyState
            icon={BellOff}
            illustration="signal"
            title="You're all caught up"
            body="Bill reminders, budget alerts, and goal milestones will land here as they happen."
          />
        </Card>
      )}
      {!isLoading && allResults.length > 0 && filteredResults.length === 0 && (
        <Card>
          <EmptyState icon={BellOff} title="No matching notifications" body="Try a different severity filter." />
        </Card>
      )}

      <Grid cols={2} gap={4}>
        {filteredResults.map((n) => (
          <Card
            key={n.id}
            interactive={!n.read_at}
            onClick={!n.read_at ? () => markRead.mutate(n.id) : undefined}
            style={{ opacity: n.read_at ? 0.6 : 1 }}
          >
            <Inline justify="between" gap={2} style={{ marginBottom: "var(--lf-space-2)" }}>
              <Badge tone={SEVERITY_TONE[n.severity] ?? "neutral"}>{n.type.replace(/_/g, " ")}</Badge>
              {!n.read_at && <Badge tone="neutral">New</Badge>}
            </Inline>
            <p className="lf-insight-title">{n.title}</p>
            {n.body && <p className="lf-insight-body">{n.body}</p>}
            <Text tone="tertiary" size="sm" style={{ marginTop: "var(--lf-space-2)" }}>
              {formatDateLong(n.created_at)}
            </Text>
          </Card>
        ))}
      </Grid>

      {nextCursor && (
        <Inline justify="center" style={{ marginTop: "var(--lf-space-4)" }}>
          <Button variant="secondary" onClick={loadMore} loading={loadingMore}>
            Load more
          </Button>
        </Inline>
      )}
    </>
  );
}
