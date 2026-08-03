import { LogOut, Monitor, Moon, Settings, Sun } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useDismiss } from "../../hooks/useDismiss";
import { useAuth } from "../../lib/AuthContext";
import { useTheme, type Theme } from "../../lib/useTheme";

const THEME_OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "Auto", icon: Monitor },
];

function displayName(user: { first_name?: string; last_name?: string; email: string } | null): string {
  if (!user) return "Account";
  const full = [user.first_name, user.last_name].filter(Boolean).join(" ");
  return full || user.email;
}

export function ProfileMenu() {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const ref = useDismiss<HTMLDivElement>(open, () => setOpen(false));

  const name = displayName(user);
  const initial = (user?.first_name || user?.email || "?").charAt(0).toUpperCase();

  return (
    <div className="lf-menu-anchor" ref={ref}>
      <button
        type="button"
        className="lf-avatar-btn"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="lf-avatar" aria-hidden="true">
          {initial}
        </span>
        <span className="lf-avatar-name">{user?.first_name || name}</span>
      </button>

      {open && (
        <div className="lf-menu" role="menu" aria-label="Account">
          <div className="lf-menu-header">
            <div style={{ fontWeight: "var(--lf-weight-semibold)", fontSize: "var(--lf-text-sm)" }}>{name}</div>
            {user?.email && (
              <div className="lf-notif-row-time" style={{ margin: 0 }}>
                {user.email}
              </div>
            )}
          </div>

          <div
            className="lf-theme-toggle"
            role="group"
            aria-label="Color theme"
          >
            {THEME_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                aria-pressed={theme === opt.value}
                onClick={() => setTheme(opt.value)}
              >
                <opt.icon size={14} strokeWidth={1.8} aria-hidden="true" />
                {opt.label}
              </button>
            ))}
          </div>

          <div className="lf-menu-sep" />

          <Link to="/settings" role="menuitem" className="lf-menu-item" onClick={() => setOpen(false)}>
            <Settings size={16} strokeWidth={1.8} aria-hidden="true" />
            Settings
          </Link>

          <button
            type="button"
            role="menuitem"
            className="lf-menu-item lf-menu-item--danger"
            onClick={async () => {
              setOpen(false);
              await logout();
              // A hard navigation clears all in-memory query caches with the session.
              window.location.href = "/logged-out";
            }}
          >
            <LogOut size={16} strokeWidth={1.8} aria-hidden="true" />
            Log out
          </button>
        </div>
      )}
    </div>
  );
}
