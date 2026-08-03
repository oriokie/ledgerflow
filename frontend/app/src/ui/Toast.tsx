import { CheckCircle2, Info } from "lucide-react";
import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";
import { ToastContext, type ToastFn } from "./toastContext";

interface ToastItem {
  id: number;
  message: string;
  tone: "success" | "info";
}

const DEFAULT_DURATION = 3200;

/**
 * Hosts the toast state and the fixed viewport. Toasts confirm that an action
 * landed — short, quiet, self-dismissing — the feedback layer mutations were
 * missing. The viewport is `role="status"` + `aria-live="polite"` so screen
 * readers hear confirmations without being interrupted.
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

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="lf-toast-viewport" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="lf-toast lf-toast--enter">
            {t.tone === "success" ? (
              <CheckCircle2 size={16} strokeWidth={2} aria-hidden="true" style={{ color: "var(--lf-status-success)" }} />
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
