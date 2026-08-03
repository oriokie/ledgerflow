import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications } from "../hooks/useNotifications";
import { formatDateLong } from "../lib/money";
import { BellOff } from "lucide-react";
import { Badge, Button, Card, EmptyState, Grid, Inline, LoadingBlock, PageHeader, Text } from "../ui";

const SEVERITY_TONE: Record<string, "neutral" | "warning" | "danger"> = {
  info: "neutral",
  warning: "warning",
  critical: "danger",
};

export function NotificationsPage() {
  const { data, isLoading } = useNotifications(false);
  const markRead = useMarkNotificationRead();
  const markAllRead = useMarkAllNotificationsRead();

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

      {isLoading && <LoadingBlock />}
      {!isLoading && data?.results.length === 0 && (
        <Card>
          <EmptyState
            icon={BellOff}
            title="You're all caught up"
            body="Bill reminders, budget alerts, and goal milestones will land here as they happen."
          />
        </Card>
      )}

      <Grid cols={2} gap={4}>
        {data?.results.map((n) => (
          <Card
            key={n.id}
            style={{ opacity: n.read_at ? 0.6 : 1, cursor: n.read_at ? "default" : "pointer" }}
          >
            <div
              onClick={() => {
                if (!n.read_at) markRead.mutate(n.id);
              }}
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
            </div>
          </Card>
        ))}
      </Grid>
    </>
  );
}
