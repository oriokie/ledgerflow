import {
  Activity,
  BadgePercent,
  Building2,
  CreditCard,
  FileText,
  Gauge,
  LayoutDashboard,
  LifeBuoy,
  LogOut,
  type LucideIcon,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
  Layers,
  Users,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useAuth } from "../../lib/AuthContext";
import { useProductIdentity } from "../../lib/useProductIdentity";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import type { PlatformStaff } from "../../api/platform";
import { useCapability, usePlatformMe, usePlatformNotifications } from "../../hooks/usePlatform";
import { Badge, Button, LoadingBlock, Modal, Textarea, ToastProvider } from "../../ui";
import { RouteErrorBoundary } from "../RouteErrorBoundary";

/**
 * Navigation for the platform workspace.
 *
 * Each entry declares the capability that makes it meaningful. An operator
 * only ever sees the sections they can actually use — a Finance user has no
 * business staring at a Staff tab that will 403. This is presentation, not
 * enforcement: the API checks the same capability independently.
 */
interface NavEntry {
  to: string;
  label: string;
  icon: LucideIcon;
  capability: string;
  end?: boolean;
}

/**
 * Grouped by the question the operator is answering, the same principle the
 * customer rail was rebuilt on in Phase 5. Eleven flat entries is a list to be
 * read; four groups is a structure to be scanned — and an operator arriving
 * mid-incident is scanning, not reading.
 */
const NAV_GROUPS: { label: string; items: NavEntry[] }[] = [
  {
    label: "Overview",
    items: [
      {
        to: "/admin",
        label: "Dashboard",
        icon: LayoutDashboard,
        capability: "platform.dashboard.view",
        end: true,
      },
      { to: "/admin/tenants", label: "Customers", icon: Building2, capability: "tenant.read" },
      { to: "/admin/analytics", label: "Analytics", icon: Gauge, capability: "platform.analytics.read" },
    ],
  },
  {
    label: "Revenue",
    items: [
      { to: "/admin/billing", label: "Billing", icon: CreditCard, capability: "billing.read" },
      { to: "/admin/invoices", label: "Invoices", icon: FileText, capability: "billing.read" },
      { to: "/admin/dunning", label: "Recovery", icon: LifeBuoy, capability: "dunning.read" },
      { to: "/admin/coupons", label: "Promotions", icon: BadgePercent, capability: "coupon.read" },
      { to: "/admin/plans", label: "Plans", icon: Layers, capability: "subscription.read" },
    ],
  },
  {
    label: "Operations",
    items: [{ to: "/admin/health", label: "System", icon: Activity, capability: "health.read" }],
  },
  {
    label: "Governance",
    items: [
      { to: "/admin/audit", label: "Audit", icon: ScrollText, capability: "audit.read" },
      { to: "/admin/staff", label: "Access", icon: Users, capability: "staff.read" },
      { to: "/admin/settings", label: "Settings", icon: SlidersHorizontal, capability: "health.read" },
    ],
  },
];

/** Flattened — the command palette and capability filtering work on one list. */
const NAV: NavEntry[] = NAV_GROUPS.flatMap((g) => g.items);
;

/**
 * Gate for the whole `/admin` tree.
 *
 * Deliberately does not redirect a non-staff user to the customer app. A
 * redirect would confirm that `/admin` exists and that they simply lack
 * access; a flat refusal tells a probing visitor nothing they did not already
 * know. Operators reach this URL from a bookmark, never by discovery.
 */
export function AdminGuard({ children }: { children: ReactNode }) {
  const { data: staff, isLoading, isError } = usePlatformMe();

  if (isLoading) return <LoadingBlock label="Checking platform access…" />;

  if (isError || !staff) {
    return (
      <div className="lf-admin-denied" role="alert">
        <ShieldCheck size={32} aria-hidden />
        <h1>Not available</h1>
        <p>This area isn&rsquo;t available for your account.</p>
        <a href="/">Return to LedgerFlow</a>
      </div>
    );
  }
  return <>{children}</>;
}

/**
 * The persistent platform shell.
 *
 * Visually distinct from the customer app on purpose — a darker rail and an
 * explicit "Platform" wordmark. An operator with both apps open needs to know
 * at a glance which one they are about to act in, because the actions here
 * affect somebody else's account.
 */
export function AdminShell() {
  const { data: staff } = usePlatformMe();
  const can = useCapability(staff);
  const navigate = useNavigate();
  const [paletteOpen, setPaletteOpen] = useState(false);

  const { data: alerts } = usePlatformNotifications({ open: "true", page_size: 5 });
  const openAlertCount = alerts?.count ?? 0;

  const visibleNav = useMemo(() => NAV.filter((entry) => can(entry.capability)), [can]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      }
      if (event.key === "Escape") setPaletteOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  /* Cool slate, signal amber, compact, square. See tokens.css. */
  useProductIdentity("platform");

  return (
    <ToastProvider>
      <div className="lf-admin">
        {/* The customer shell has one and this did not — an operator navigating
            by keyboard had to tab through the whole rail on every page load.
            WCAG 2.4.1 (Bypass Blocks). Reuses the existing visually-hidden
            styling so the two shells behave identically. */}
        <a className="lf-skip-link" href="#main">
          Skip to content
        </a>
        <aside className="lf-admin-rail" aria-label="Platform navigation">
          <div className="lf-admin-brand">
            <ShieldCheck size={18} aria-hidden />
            <span>
              LedgerFlow <strong>Platform</strong>
            </span>
          </div>

          <nav className="lf-admin-nav">
            {NAV_GROUPS.map((group) => {
              const items = group.items.filter((entry) => can(entry.capability));
              // A group heading with nothing under it tells an operator only
              // that there is something they cannot see.
              if (items.length === 0) return null;
              return (
                <div key={group.label} className="lf-admin-nav-group">
                  <p className="lf-admin-nav-group-label">{group.label}</p>
                  {items.map(({ to, label, icon: Icon, end }) => (
                    <NavLink
                      key={to}
                      to={to}
                      end={end}
                      className={({ isActive }) =>
                        isActive ? "lf-admin-nav-link lf-admin-nav-link--active" : "lf-admin-nav-link"
                      }
                    >
                      <Icon size={16} aria-hidden />
                      <span>{label}</span>
                      {to === "/admin/health" && openAlertCount > 0 && (
                        <span
                          className="lf-admin-nav-count"
                          aria-label={`${openAlertCount} open alerts`}
                        >
                          {openAlertCount}
                        </span>
                      )}
                    </NavLink>
                  ))}
                </div>
              );
            })}
          </nav>

          <AdminIdentity staff={staff} />
        </aside>

        <div className="lf-admin-main">
          <header className="lf-admin-topbar">
            <button
              type="button"
              className="lf-admin-search"
              onClick={() => setPaletteOpen(true)}
              aria-label="Open command palette"
            >
              <span>Jump to…</span>
              <kbd>⌘K</kbd>
            </button>
            <a className="lf-admin-exit" href="/">
              Back to LedgerFlow
            </a>
          </header>

          <main className="lf-admin-content" id="main">
            <RouteErrorBoundary>
              <Outlet />
            </RouteErrorBoundary>
          </main>
        </div>

        <CommandPalette
          open={paletteOpen}
          entries={visibleNav}
          onClose={() => setPaletteOpen(false)}
          onPick={(to) => {
            setPaletteOpen(false);
            navigate(to);
          }}
        />
      </div>
    </ToastProvider>
  );
}

function AdminIdentity({ staff }: { staff?: PlatformStaff }) {
  const { logout } = useAuth();
  if (!staff) return null;
  const roleLabel = staff.role.replace(/_/g, " ");
  return (
    <div className="lf-admin-identity">
      <p className="lf-admin-identity-email">{staff.email}</p>
      <Badge tone="neutral">{roleLabel}</Badge>

      {/* The console had no way out of it. "Back to LedgerFlow" is not a sign
          out — and for a platform account it is a dead end, because the
          customer app has no workspace to send an operator to and bounces
          them straight back here. An operator who can suspend somebody's
          account could not end their own session, which on a shared or
          unattended machine is the whole problem.

          Hard navigation rather than a router push, for the same reason the
          customer app does it: it drops every in-memory query cache along
          with the session, so nothing another operator sees was fetched
          under the previous one's credentials. */}
      <button
        type="button"
        className="lf-admin-signout"
        onClick={async () => {
          await logout();
          window.location.href = "/logged-out";
        }}
      >
        <LogOut size={15} strokeWidth={1.8} aria-hidden="true" />
        Sign out
      </button>
    </div>
  );
}

function CommandPalette({
  open,
  entries,
  onClose,
  onPick,
}: {
  open: boolean;
  entries: NavEntry[];
  onClose: () => void;
  onPick: (to: string) => void;
}) {
  const [query, setQuery] = useState("");
  const matches = entries.filter((entry) =>
    entry.label.toLowerCase().includes(query.trim().toLowerCase()),
  );

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  if (!open) return null;

  return (
    <Modal open={open} onClose={onClose} title="Jump to">
      <input
        className="lf-input"
        autoFocus
        value={query}
        placeholder="Search sections…"
        aria-label="Search sections"
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && matches[0]) onPick(matches[0].to);
        }}
      />
      <ul className="lf-admin-palette-list">
        {matches.map(({ to, label, icon: Icon }) => (
          <li key={to}>
            <button type="button" className="lf-admin-palette-item" onClick={() => onPick(to)}>
              <Icon size={15} aria-hidden />
              {label}
            </button>
          </li>
        ))}
        {matches.length === 0 && <li className="lf-admin-palette-empty">No matching section.</li>}
      </ul>
    </Modal>
  );
}

/**
 * The confirmation dialog for any audited action.
 *
 * The reason field is required and free-text rather than a dropdown of canned
 * options. A dropdown produces a log where every entry says "Other", which is
 * indistinguishable from no log at all; forcing a sentence means the person
 * reading this in six months learns something. The minimum length is enforced
 * here and again in the API — the client copy is a courtesy so the operator
 * finds out before the round trip.
 */
export function ReasonDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  destructive = false,
  minLength = 5,
  pending = false,
  error,
  onConfirm,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
  minLength?: number;
  pending?: boolean;
  error?: string | null;
  onConfirm: (reason: string) => void;
  onClose: () => void;
  children?: ReactNode;
}) {
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (!open) setReason("");
  }, [open]);

  const tooShort = reason.trim().length < minLength;

  return (
    <Modal open={open} onClose={onClose} title={title}>
      {description && <p className="lf-admin-dialog-description">{description}</p>}
      {children}
      <Textarea
        label="Reason"
        hint={`Recorded permanently in the audit log. At least ${minLength} characters.`}
        error={error ?? undefined}
        value={reason}
        rows={3}
        autoFocus
        onChange={(event) => setReason(event.target.value)}
        placeholder="Why is this action being taken?"
      />
      <div className="lf-admin-dialog-actions">
        <Button variant="ghost" onClick={onClose} type="button">
          Cancel
        </Button>
        <Button
          variant={destructive ? "danger" : "primary"}
          type="button"
          disabled={tooShort || pending}
          onClick={() => onConfirm(reason.trim())}
        >
          {pending ? "Working…" : confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
