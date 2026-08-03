import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";

type ModalSize = "sm" | "md" | "lg" | "xl";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  /** One line of context under the title — what this dialog is for. */
  description?: ReactNode;
  children: ReactNode;
  /** Trailing footer actions (the primary button). */
  footer?: ReactNode;
  /** Leading footer actions — Cancel, or a destructive escape hatch. */
  footerStart?: ReactNode;
  size?: ModalSize;
  /** @deprecated use size="lg" */
  wide?: boolean;
}

/**
 * Dialog widths. `xl` is the form width: wide enough for two-column field
 * rows without the eye having to travel, narrow enough to stay a dialog
 * rather than a page.
 */
const WIDTH: Record<ModalSize, string> = {
  sm: "min(400px, calc(100vw - var(--lf-space-8)))",
  md: "min(480px, calc(100vw - var(--lf-space-8)))",
  lg: "min(680px, calc(100vw - var(--lf-space-8)))",
  xl: "min(600px, calc(100vw - var(--lf-space-8)))",
};

/**
 * Native <dialog> styled by `.lf-modal`. The platform gives focus containment,
 * Esc-to-close, and a backdrop for free — no portal or focus-trap library.
 *
 * Structure is header / scrolling body / pinned footer, so a long form scrolls
 * under its own title while the actions stay reachable. The footer splits into
 * a leading slot (`footerStart`, conventionally Cancel) and a trailing slot
 * (`footer`, the primary action); a modal that only passes `footer` still gets
 * a correctly right-aligned button.
 */
export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  footerStart,
  size = "md",
  wide,
}: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const resolvedSize: ModalSize = wide ? "lg" : size;
  const titleId = useId();
  const descId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="lf-modal lf-modal--structured"
      style={{ width: WIDTH[resolvedSize] }}
      aria-labelledby={titleId}
      aria-describedby={description ? descId : undefined}
      onClose={onClose}
      onClick={(e) => {
        // Clicks land on the dialog element itself only when they hit the
        // backdrop; anything inside a zone stops here naturally.
        if (e.target === ref.current) onClose();
      }}
    >
      <div className="lf-modal-head">
        <div>
          <h2 className="lf-modal-title" id={titleId}>
            {title}
          </h2>
          {description && (
            <p className="lf-modal-desc" id={descId}>
              {description}
            </p>
          )}
        </div>
        <button
          className="lf-btn lf-btn--ghost lf-iconbtn"
          type="button"
          onClick={onClose}
          aria-label="Close"
        >
          <X size={18} strokeWidth={1.8} aria-hidden="true" />
        </button>
      </div>

      <div className="lf-modal-body">{children}</div>

      {(footer || footerStart) && (
        <div className="lf-modal-footer">
          <div className="lf-modal-footer-start">{footerStart}</div>
          <div className="lf-modal-footer-end">{footer}</div>
        </div>
      )}
    </dialog>
  );
}
