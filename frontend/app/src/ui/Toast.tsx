import clsx from "clsx";
import { AlertCircle, CheckCircle2, Info } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ToastContext, type ToastFn } from "./toastContext";
import { setToastNotifier } from "./toastBridge";

interface ToastItem {
  id: number;
  message: string;
  tone: "success" | "info" | "danger";
}

const DEFAULT_DURATION = 3200;

/**
 * Hosts the toast state and the fixed viewport. Toasts confirm that an action
 * landed — short, quiet, self-dismissing — the feedback layer mutations were
 * missing. The viewport is `role="status"` + `aria-live="polite"` so success/
 * info toasts are heard without interrupting. Danger toasts additionally
 * carry their own `role="alert"` (matching how Banner distinguishes danger
 * from success/info), which takes precedence for that element so failures
 * interrupt instead of waiting their turn.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback<ToastFn>(
    (message, options) => {
      const id = nextId.current++;
      setToasts((prev) => [...prev.slice(-2), { id, message, tone: options?.tone ?? "success" }]);
      window.setTimeout(() => dismiss(id), options?.duration ?? DEFAULT_DURATION);
    },
    [dismiss],
  );

  const value = useMemo(() => toast, [toast]);

  // Register this provider's toast fn on the module-level bridge so code
  // outside the React tree (the QueryClient's default mutation onError,
  // built at module scope) can still surface a toast.
  useEffect(() => {
    setToastNotifier(toast);
    return () => setToastNotifier(null);
  }, [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="lf-toast-viewport" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={clsx("lf-toast", "lf-toast--enter", t.tone === "danger" && "lf-toast--danger")}
            role={t.tone === "danger" ? "alert" : undefined}
          >
            {t.tone === "success" ? (
              <CheckCircle2 size={16} strokeWidth={2} aria-hidden="true" style={{ color: "var(--lf-status-success)" }} />
            ) : t.tone === "danger" ? (
              <AlertCircle size={16} strokeWidth={2} aria-hidden="true" style={{ color: "var(--lf-status-danger)" }} />
            ) : (
              <Info size={16} strokeWidth={2} aria-hidden="true" />
            )}
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
