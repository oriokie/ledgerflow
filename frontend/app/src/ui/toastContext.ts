import { createContext, useContext } from "react";

export interface ToastOptions {
  /** "success" gets a check icon; "info" an info icon; "danger" an alert
   * icon in the status-danger color and announces via role="alert". */
  tone?: "success" | "info" | "danger";
  /** ms before auto-dismiss. */
  duration?: number;
}

export type ToastFn = (message: string, options?: ToastOptions) => void;

/** Default is a safe no-op so components (and tests) work without a provider. */
export const ToastContext = createContext<ToastFn>(() => {});

/** Fire a transient confirmation, e.g. `toast("Marked as paid")`. Announced
 * politely to assistive tech via the viewport's live region. */
export function useToast(): ToastFn {
  return useContext(ToastContext);
}
