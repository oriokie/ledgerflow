import { AlertTriangle, Check, ChevronDown, RotateCcw } from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { SETTINGS_NAV } from "./nav";

/** What an autosaving panel is currently doing. */
export type SaveState = "idle" | "saving" | "saved" | "error";

/**
 * The affordance that replaces a "Save changes" button.
 *
 * Autosave without a status indicator is strictly worse than a button: the
 * button at least told you when your work was committed. So this has to do
 * three things a button did for free — say that a save is in flight, confirm
 * that it landed, and be unmissable when it did not.
 *
 * `role="status"` rather than `aria-live="assertive"`: a save confirmation
 * should not interrupt what someone is typing. The failure case carries its own
 * `role="alert"`, because that one *should*.
 */
export function SaveStatus({
  state,
  error,
  onRetry,
}: {
  state: SaveState;
  error?: string | null;
  onRetry?: () => void;
}) {
  if (state === "error") {
    return (
      <p className="lf-save-status" data-state="error" role="alert">
        <AlertTriangle size={14} strokeWidth={2} aria-hidden="true" />
        {error ?? "Couldn't save your changes."}
        {onRetry && (
          <button type="button" className="lf-save-retry" onClick={onRetry}>
            <RotateCcw size={13} strokeWidth={2} aria-hidden="true" />
            Try again
          </button>
        )}
      </p>
    );
  }

  return (
    <p className="lf-save-status" data-state={state} role="status">
      {state === "saving" && "Saving…"}
      {state === "saved" && (
        <>
          <Check size={14} strokeWidth={2.2} aria-hidden="true" />
          All changes saved
        </>
      )}
    </p>
  );
}

/** Grouped settings sub-navigation. Renders each group with its label and the
 * items as active-aware links, shared by the sidebar and the mobile row. */
export function SettingsNav() {
  return (
    <nav className="lf-settings-nav" aria-label="Settings sections">
      {SETTINGS_NAV.map((group) => (
        <div key={group.label} className="lf-settings-nav-group">
          <p className="lf-settings-nav-group-label">{group.label}</p>
          {group.items.map((item) => (
            <NavLink
              key={item.slug}
              to={`/settings/${item.slug}`}
              className={({ isActive }) => `lf-settings-nav-link${isActive ? " is-active" : ""}`}
            >
              <item.icon size={16} strokeWidth={1.8} aria-hidden="true" />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );
}

/** A titled block of related settings — the consistent container every panel
 * builds from. */
export function SettingsSection({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="lf-settings-section">
      <div className="lf-settings-section-head">
        <div>
          <h2 className="lf-settings-section-title">{title}</h2>
          {description && <p className="lf-settings-section-desc">{description}</p>}
        </div>
        {action && <div className="lf-settings-section-action">{action}</div>}
      </div>
      <div className="lf-settings-section-body">{children}</div>
    </section>
  );
}

/** A single labelled setting: a title + optional description on the left, its
 * control on the right (stacks on narrow screens). */
export function SettingsRow({
  title,
  description,
  htmlFor,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  htmlFor?: string;
  children?: ReactNode;
}) {
  return (
    <div className="lf-settings-row">
      <div className="lf-settings-row-label">
        {htmlFor ? (
          <label htmlFor={htmlFor} className="lf-settings-row-title">
            {title}
          </label>
        ) : (
          <span className="lf-settings-row-title">{title}</span>
        )}
        {description && <p className="lf-settings-row-desc">{description}</p>}
      </div>
      {children != null && <div className="lf-settings-row-control">{children}</div>}
    </div>
  );
}

/**
 * A visually separated region for irreversible actions.
 *
 * Deliberately not just a red button in a normal section: the destructive
 * surface is pushed to the bottom of the panel, given its own heading, and
 * outlined in a restrained red. The accent is a border and a tinted header —
 * not a filled red block — because a permanently alarming panel stops being
 * read at all. The alarm belongs to the moment of action, not the container.
 */
export function DangerZone({
  title = "Danger zone",
  description,
  children,
}: {
  title?: string;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="lf-danger-zone" aria-labelledby="danger-zone-title">
      <div className="lf-danger-zone-head">
        <AlertTriangle size={16} strokeWidth={2} aria-hidden="true" />
        <div>
          <h2 className="lf-danger-zone-title" id="danger-zone-title">
            {title}
          </h2>
          {description && <p className="lf-danger-zone-desc">{description}</p>}
        </div>
      </div>
      <div className="lf-danger-zone-body">{children}</div>
    </section>
  );
}

/**
 * A collapsible disclosure for power-user options. Keeps advanced settings
 * discoverable (clearly labelled, one click away) without cluttering the
 * default view. Collapsed by default.
 */
export function SettingsAdvanced({ label = "Advanced options", children }: { label?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="lf-settings-advanced" data-open={open}>
      <button
        type="button"
        className="lf-settings-advanced-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronDown size={16} strokeWidth={2} aria-hidden="true" className="lf-settings-advanced-chevron" />
        {label}
      </button>
      {open && <div className="lf-settings-advanced-body">{children}</div>}
    </div>
  );
}
