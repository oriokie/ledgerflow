import { Check, ChevronsUpDown, Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDismiss } from "../../hooks/useDismiss";
import { useAuth } from "../../lib/AuthContext";

export function WorkspaceSwitcher() {
  const { activeWorkspace, workspaces, switchWorkspace } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useDismiss<HTMLDivElement>(open, () => setOpen(false));

  const initial = (activeWorkspace?.tenant.name ?? "?").charAt(0).toUpperCase();

  return (
    <div className="lf-menu-anchor" ref={ref}>
      <button
        type="button"
        className="lf-workspace-switcher"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="lf-workspace-avatar" aria-hidden="true">
          {initial}
        </span>
        <span className="lf-avatar-name">{activeWorkspace?.tenant.name ?? "Select workspace"}</span>
        <ChevronsUpDown size={14} strokeWidth={1.8} aria-hidden="true" />
      </button>

      {open && (
        <div className="lf-menu" role="menu" aria-label="Switch workspace" style={{ left: 0, right: "auto" }}>
          <p className="lf-rail-section-label" style={{ padding: "var(--lf-space-1) var(--lf-space-3)" }}>
            Workspaces
          </p>
          {workspaces.map((ws) => {
            const active = ws.tenant.id === activeWorkspace?.tenant.id;
            return (
              <button
                key={ws.tenant.id}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                className="lf-menu-item"
                onClick={() => {
                  setOpen(false);
                  if (!active) switchWorkspace(ws.tenant.id);
                }}
              >
                <span className="lf-workspace-avatar" aria-hidden="true">
                  {ws.tenant.name.charAt(0).toUpperCase()}
                </span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: "block", fontWeight: "var(--lf-weight-medium)" }}>
                    {ws.tenant.name}
                  </span>
                  <span className="lf-notif-row-time" style={{ margin: 0, textTransform: "capitalize" }}>
                    {ws.role}
                  </span>
                </span>
                {active && <Check size={16} strokeWidth={2} aria-hidden="true" />}
              </button>
            );
          })}
          <div className="lf-menu-sep" />
          <button
            type="button"
            role="menuitem"
            className="lf-menu-item"
            onClick={() => {
              setOpen(false);
              navigate("/workspaces");
            }}
          >
            <Plus size={16} strokeWidth={1.8} aria-hidden="true" />
            New workspace
          </button>
        </div>
      )}
    </div>
  );
}
