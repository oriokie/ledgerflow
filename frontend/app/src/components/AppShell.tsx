import { Menu, Plus, Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { CommandPalette } from "./shell/CommandPalette";
import { ShortcutHelp } from "./shell/ShortcutHelp";
import { isTypingTarget, matchShortcut } from "./shell/shortcuts";
import { MobileTabBar } from "./shell/MobileTabBar";
import { PinViewButton } from "./shell/PinViewButton";
import { NotificationCenter } from "./shell/NotificationCenter";
import { OfflineIndicator } from "./shell/OfflineIndicator";
import { PlanBanner } from "./shell/PlanBanner";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import { ProfileMenu } from "./shell/ProfileMenu";
import { BrandMark, SidebarNav } from "./shell/SidebarNav";
import { WorkspaceSwitcher } from "./shell/WorkspaceSwitcher";
import { ToastProvider } from "../ui";

/**
 * Advertise the shortcut the user's keyboard actually has. Showing ⌘K to a
 * Windows user is a small lie that makes the hint useless. Resolved once at
 * module load — the platform does not change mid-session.
 */
const IS_APPLE =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent);
const shortcutLabel = IS_APPLE ? "⌘K" : "Ctrl K";

/**
 * The persistent application shell wrapping every authenticated page.
 *
 * Layout by breakpoint:
 *   • ≥1024px — fixed left rail + topbar.
 *   • <1024px — topbar with a hamburger that opens an off-canvas nav drawer;
 *     the rail is hidden (CSS-driven so there's no layout flash on resize).
 *
 * The topbar hosts workspace switching, ⌘K global search, the notification
 * center, and the profile menu — consistent across all routes.
 */
export function AppShell() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  /** Holds the `g` prefix between keypresses (G then T = go to transactions). */
  const pendingGoto = useRef(false);

  // Close the mobile drawer whenever navigation happens.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  // Global keyboard layer. One listener, one pure matcher (see shortcuts.ts),
  // so behavior is testable and there's a single place that decides whether a
  // keypress belongs to the app or to whatever the user is typing in.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const action = matchShortcut({
        key: e.key,
        metaKey: e.metaKey,
        ctrlKey: e.ctrlKey,
        altKey: e.altKey,
        shiftKey: e.shiftKey,
        pendingGoto: pendingGoto.current,
        typing: isTypingTarget(e.target),
      });

      // A `g` prefix stays pending for a beat; anything else clears it.
      if (action?.type !== "await-goto") pendingGoto.current = false;
      if (!action) return;

      switch (action.type) {
        case "palette":
          e.preventDefault();
          setSearchOpen((v) => !v);
          break;
        case "await-goto":
          pendingGoto.current = true;
          // Don't strand the prefix: if no second key lands, forget it.
          window.setTimeout(() => {
            pendingGoto.current = false;
          }, 1500);
          break;
        case "goto":
          e.preventDefault();
          navigate(action.to);
          break;
        case "new-transaction":
          e.preventDefault();
          navigate("/transactions?add=1");
          break;
        case "new-account":
          e.preventDefault();
          navigate("/accounts?add=1");
          break;
        case "help":
          e.preventDefault();
          setHelpOpen(true);
          break;
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  // Prevent background scroll while the drawer is open, close it on Escape,
  // and hand focus back to the trigger afterwards.
  //
  // Modals get all of this free from <dialog>, but the drawer is a plain
  // element, so it has to be wired by hand — otherwise a keyboard user can open
  // the menu and have no way out except Tab-cycling through every link, and
  // focus is left stranded on a hidden element once it closes.
  useEffect(() => {
    if (!drawerOpen) return;

    const prevOverflow = document.body.style.overflow;
    const returnFocusTo = document.activeElement as HTMLElement | null;
    document.body.style.overflow = "hidden";

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setDrawerOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);

    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKey);
      returnFocusTo?.focus?.();
    };
  }, [drawerOpen]);

  return (
    <ToastProvider>
    <div className="lf-shell">
      <a className="lf-skip-link" href="#main">
        Skip to content
      </a>

      <OfflineIndicator />

      {/* Desktop rail */}
      <nav className="lf-rail" aria-label="Primary">
        <NavLink className="lf-rail-brand" to="/">
          <BrandMark />
        </NavLink>
        <SidebarNav />
      </nav>

      {/* Mobile / tablet drawer */}
      {drawerOpen && (
        <>
          <div className="lf-drawer-backdrop" onClick={() => setDrawerOpen(false)} aria-hidden="true" />
          <nav className="lf-drawer" aria-label="Primary" role="dialog" aria-modal="true">
            <div className="lf-drawer-head">
              <NavLink className="lf-rail-brand" to="/" style={{ padding: 0 }}>
                <BrandMark />
              </NavLink>
              <button
                type="button"
                className="lf-btn lf-btn--ghost lf-iconbtn"
                aria-label="Close menu"
                onClick={() => setDrawerOpen(false)}
              >
                <X size={18} strokeWidth={1.8} aria-hidden="true" />
              </button>
            </div>
            <SidebarNav onNavigate={() => setDrawerOpen(false)} />
          </nav>
        </>
      )}

      <div className="lf-shell-main">
        <header className="lf-topbar">
          <div className="lf-topbar-left">
            <button
              type="button"
              className="lf-btn lf-btn--ghost lf-iconbtn lf-hamburger"
              aria-label="Open menu"
              aria-expanded={drawerOpen}
              onClick={() => setDrawerOpen(true)}
            >
              <Menu size={18} strokeWidth={1.8} aria-hidden="true" />
            </button>
            <WorkspaceSwitcher />
          </div>

          <div className="lf-topbar-spacer" />

          <button
            type="button"
            className="lf-search-trigger"
            onClick={() => setSearchOpen(true)}
            aria-label="Search"
          >
            <Search size={15} strokeWidth={1.8} aria-hidden="true" />
            <span className="lf-search-trigger-label">Search…</span>
            <kbd className="lf-kbd">{shortcutLabel}</kbd>
          </button>

          <PinViewButton />
          <NotificationCenter />
          <ProfileMenu />

          <Link className="lf-btn lf-btn--primary" to="/transactions?add=1" aria-label="Add transaction">
            <Plus size={16} strokeWidth={2} aria-hidden="true" />
            <span className="lf-hide-xs">Add transaction</span>
          </Link>
        </header>

        <main className="lf-content" id="main">
          <PlanBanner />
          <RouteErrorBoundary key={location.pathname}>
            <Outlet />
          </RouteErrorBoundary>
        </main>
      </div>

      <MobileTabBar />

      <CommandPalette open={searchOpen} onClose={() => setSearchOpen(false)} />
      <ShortcutHelp open={helpOpen} onClose={() => setHelpOpen(false)} />
    </div>
    </ToastProvider>
  );
}
