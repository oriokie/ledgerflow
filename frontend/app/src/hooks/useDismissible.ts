import { useCallback, useState } from "react";

const PREFIX = "lf.dismissed.";

/**
 * Remembers that a user dismissed something, across sessions.
 *
 * Guidance surfaces — the setup checklist, tips, one-off banners — have to be
 * dismissible or they become nagging. But a dismissal that resets on refresh is
 * arguably worse than none: the user told us once and we ignored them.
 *
 * localStorage rather than the server, deliberately. This is a per-person,
 * per-device UI preference with no financial meaning; round-tripping it would
 * add an API surface, a migration and a failure mode to something that does not
 * matter if it's lost. Access is wrapped because storage throws in private
 * browsing modes and inside sandboxed frames — a banner is never worth a crash.
 */
export function useDismissible(key: string): [boolean, () => void] {
  const storageKey = `${PREFIX}${key}`;

  const [dismissed, setDismissed] = useState(() => {
    try {
      return window.localStorage.getItem(storageKey) === "1";
    } catch {
      return false;
    }
  });

  const dismiss = useCallback(() => {
    setDismissed(true);
    try {
      window.localStorage.setItem(storageKey, "1");
    } catch {
      // Non-fatal: the dismissal still holds for this session.
    }
  }, [storageKey]);

  return [dismissed, dismiss];
}
