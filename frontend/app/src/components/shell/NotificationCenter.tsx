import { Bell, CheckCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useDismiss } from "../../hooks/useDismiss";
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from "../../hooks/useNotifications";
import { formatRelativeTime } from "../../lib/money";
import { Spinner } from "../../ui";

const PREVIEW_LIMIT = 6;

/**
 * Bell + inline dropdown showing the most recent notifications. Reading an
 * unread item marks it read; a footer link leads to the full history page.
 * The unread count drives both the dot and the accessible label.
 */
export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const ref = useDismiss<HTMLDivElement>(open, () => setOpen(false));
  const { data, isLoading } = useNotifications();
  const markRead = useMarkNotificationRead();
  const markAll = useMarkAllNotificationsRead();

  const unread = data?.unread_count ?? 0;
  const items = data?.results.slice(0, PREVIEW_LIMIT) ?? [];

  return (
    <div className="lf-menu-anchor" ref={ref}>
      <button
        type="button"
        className="lf-btn lf-btn--ghost lf-iconbtn"
        style={{ position: "relative" }}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        onClick={() => setOpen((v) => !v)}
      >
        <Bell size={18} strokeWidth={1.8} aria-hidden="true" />
        {unread > 0 && <span className="lf-notif-dot" aria-hidden="true" />}
      </button>

      {open && (
        <div className="lf-menu lf-notif-panel" role="menu" aria-label="Notifications">
          <div className="lf-notif-panel-header">
            <span className="lf-notif-panel-title">
              Notifications{unread > 0 ? ` (${unread})` : ""}
            </span>
            <button
              type="button"
              className="lf-btn lf-btn--ghost lf-btn--sm"
              onClick={() => markAll.mutate()}
              disabled={markAll.isPending || unread === 0}
            >
              <CheckCheck size={14} strokeWidth={1.8} aria-hidden="true" />
              Mark all read
            </button>
          </div>

          <div className="lf-notif-scroll">
            {isLoading ? (
              <div className="lf-notif-empty">
                <Spinner /> Loading…
              </div>
            ) : items.length === 0 ? (
              <div className="lf-notif-empty">You&rsquo;re all caught up.</div>
            ) : (
              items.map((n) => (
                <button
                  key={n.id}
                  type="button"
                  className="lf-notif-row"
                  data-unread={n.read_at ? "false" : "true"}
                  data-severity={n.severity}
                  onClick={() => {
                    if (!n.read_at) markRead.mutate(n.id);
                  }}
                >
                  <span className="lf-notif-status" aria-hidden="true" />
                  <span>
                    <span className="lf-notif-row-title">{n.title}</span>
                    {n.body && <span className="lf-notif-row-body">{n.body}</span>}
                    <span className="lf-notif-row-time">{formatRelativeTime(n.created_at)}</span>
                  </span>
                </button>
              ))
            )}
          </div>

          <div className="lf-notif-panel-footer">
            <Link
              to="/notifications"
              className="lf-menu-item"
              style={{ justifyContent: "center" }}
              onClick={() => setOpen(false)}
            >
              See all notifications
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
