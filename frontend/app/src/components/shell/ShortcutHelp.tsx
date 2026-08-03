import { useEffect, useRef } from "react";
import { SHORTCUTS, type Shortcut } from "./shortcuts";

/** Renders "G then T" as two distinct keycaps with the joining word between. */
function Keys({ keys }: { keys: string }) {
  const parts = keys.split(" then ");
  return (
    <span className="lf-shortcut-keys">
      {parts.map((part, i) => (
        <span key={part + i}>
          {i > 0 && <span className="lf-shortcut-then">then</span>}
          <kbd className="lf-kbd">{part}</kbd>
        </span>
      ))}
    </span>
  );
}

const GROUPS: Shortcut["group"][] = ["General", "Actions", "Navigation"];

/**
 * The `?` shortcut sheet. A native <dialog>, so Esc-to-close and focus
 * containment come from the platform.
 *
 * Discoverability is the whole point: shortcuts that only exist in a changelog
 * may as well not exist. The palette footer and this sheet are the two places a
 * user can find out the product is keyboard-driven.
 */
export function ShortcutHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dlg = ref.current;
    if (!dlg) return;
    if (open && !dlg.open) dlg.showModal();
    if (!open && dlg.open) dlg.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="lf-modal lf-modal--structured"
      style={{ width: "min(520px, calc(100vw - var(--lf-space-8)))" }}
      aria-label="Keyboard shortcuts"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      <div className="lf-modal-head">
        <div>
          <h2 className="lf-modal-title">Keyboard shortcuts</h2>
          <p className="lf-modal-desc">Shortcuts pause while you're typing in a field.</p>
        </div>
        <button className="lf-btn lf-btn--ghost lf-iconbtn" type="button" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </div>

      <div className="lf-modal-body">
        {GROUPS.map((group) => {
          const items = SHORTCUTS.filter((s) => s.group === group);
          if (items.length === 0) return null;
          return (
            <section key={group} className="lf-shortcut-group">
              <h3 className="lf-eyebrow">{group}</h3>
              <dl className="lf-shortcut-list">
                {items.map((s) => (
                  <div key={s.keys} className="lf-shortcut-row">
                    <dt>{s.label}</dt>
                    <dd>
                      <Keys keys={s.keys} />
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          );
        })}
      </div>
    </dialog>
  );
}
