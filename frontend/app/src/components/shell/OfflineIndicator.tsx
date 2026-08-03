import { CloudOff, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { usePendingQuickAddCount } from "../../hooks/useQuickAdd";

/**
 * A slim status bar for connectivity and the offline queue.
 *
 * Renders nothing at all in the common case — online, nothing queued —
 * rather than a permanent "You're online" bar nobody needs to see. It only
 * appears when there's something to say: the connection is actually gone, or
 * something is waiting to send. That's the same restraint the debt
 * dashboard's alerts follow: a UI that announces every normal state gets
 * tuned out, including the one time it matters.
 */
export function OfflineIndicator() {
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine));
  const pendingCount = usePendingQuickAddCount();

  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  if (online && pendingCount === 0) return null;

  return (
    <div className="lf-offline-bar" role="status">
      {!online ? (
        <>
          <CloudOff size={14} strokeWidth={2} aria-hidden="true" />
          <span>
            You're offline.
            {pendingCount > 0 &&
              ` ${pendingCount} ${pendingCount === 1 ? "entry" : "entries"} will send once you're back.`}
          </span>
        </>
      ) : (
        <>
          <RefreshCw size={14} strokeWidth={2} aria-hidden="true" className="lf-offline-spin" />
          <span>Sending {pendingCount} queued {pendingCount === 1 ? "entry" : "entries"}…</span>
        </>
      )}
    </div>
  );
}
