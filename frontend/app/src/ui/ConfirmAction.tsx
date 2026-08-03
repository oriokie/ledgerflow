import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button, IconButton } from "./Button";

interface ConfirmActionProps {
  /** What the confirmed action does. Runs on the second click. */
  onConfirm: () => void | Promise<unknown>;
  /** Label for the resting-state trigger. */
  label: string;
  /** Label for the armed, destructive button. Keep it a verb. */
  confirmLabel?: string;
  /** Label for backing out. Keep it a verb too — "Keep", not "No". */
  cancelLabel?: string;
  /** Icon-only trigger (table rows, dense lists). `label` becomes its a11y name. */
  icon?: ReactNode;
  variant?: "danger" | "secondary" | "ghost";
  size?: "sm" | "md";
  disabled?: boolean;
  /**
   * Seconds before an armed control disarms itself. Prevents a stray
   * destructive button sitting armed on screen after the user moved on.
   */
  disarmAfter?: number;
}

/**
 * Inline two-step confirmation for destructive actions.
 *
 * The pattern was already used correctly in three places (budgets, bills,
 * subscriptions) and hand-rolled slightly differently each time — while three
 * other destructive actions (delete category, remove member, archive goal)
 * shipped with no confirmation at all. This consolidates the good pattern into
 * one control so the guarantee is structural rather than per-page discipline.
 *
 * Inline rather than a modal, deliberately: a modal for every small delete is
 * heavier than the action deserves and trains users to dismiss dialogs without
 * reading. A modal is still the right call for workspace-level destruction,
 * which is why closing a workspace keeps its type-the-name gate.
 *
 * Armed state auto-disarms and is announced via `aria-live`, so a screen
 * reader user learns the button's meaning changed under them.
 */
export function ConfirmAction({
  onConfirm,
  label,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  icon,
  variant = "danger",
  size = "sm",
  disabled,
  disarmAfter = 6,
}: ConfirmActionProps) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // Move focus to the confirm button so keyboard users don't have to hunt for
  // the control that just appeared.
  useEffect(() => {
    if (armed) confirmRef.current?.focus();
  }, [armed]);

  useEffect(() => {
    if (!armed || busy) return;
    const id = setTimeout(() => setArmed(false), disarmAfter * 1000);
    return () => clearTimeout(id);
  }, [armed, busy, disarmAfter]);

  const run = async () => {
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      // The row is often unmounted by the action that just succeeded.
      if (mounted.current) {
        setBusy(false);
        setArmed(false);
      }
    }
  };

  if (!armed) {
    return icon ? (
      <IconButton label={label} icon={icon} onClick={() => setArmed(true)} disabled={disabled} size={size} />
    ) : (
      <Button variant="ghost" size={size} onClick={() => setArmed(true)} disabled={disabled}>
        {label}
      </Button>
    );
  }

  return (
    <span className="lf-confirm" role="group" aria-label={`Confirm: ${label}`}>
      <span className="lf-visually-hidden" role="status">
        {label} needs confirmation.
      </span>
      <Button ref={confirmRef} variant={variant} size={size} loading={busy} onClick={run}>
        {confirmLabel}
      </Button>
      <Button variant="ghost" size={size} onClick={() => setArmed(false)} disabled={busy}>
        {cancelLabel}
      </Button>
    </span>
  );
}
