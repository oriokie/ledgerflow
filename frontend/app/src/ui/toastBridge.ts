import type { ToastFn } from "./toastContext";

/**
 * Module-level bridge so code constructed outside the React tree — notably
 * the QueryClient, which is built at module scope before ToastProvider ever
 * mounts — can still surface a toast.
 *
 * ToastProvider registers its `toast` function here via useEffect on mount
 * (and clears it on unmount). Anything that can't reach useToast() calls
 * `notifyToast` instead; before the provider has mounted (or in tests that
 * render without one) it falls back to `console.error` so the failure is
 * never silently swallowed.
 */
let notifier: ToastFn | null = null;

export function setToastNotifier(fn: ToastFn | null): void {
  notifier = fn;
}

export function notifyToast(...args: Parameters<ToastFn>): void {
  if (notifier) {
    notifier(...args);
  } else {
    console.error("[toast]", args[0]);
  }
}
