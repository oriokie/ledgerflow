import { useState } from "react";
import { NavLink } from "react-router-dom";
import { useFlag } from "../../lib/featureFlags";
import { AddActionSheet } from "./AddActionSheet";
import { tabBarItems, tabBarItemsV2 } from "./tabBarConfig";

/**
 * Fixed bottom navigation for phones/tablets (hidden ≥1024px by CSS). Gives the
 * most-used destinations a one-tap, thumb-reachable home; the hamburger drawer
 * still carries the full nav.
 *
 * Under the Phase 5 IA the centre slot is a **verb**, not a destination: the
 * thumb's best position on a phone goes to the thing people open the app to do.
 */
export function MobileTabBar() {
  const [navV2] = useFlag("navV2");
  const [adding, setAdding] = useState(false);

  if (!navV2) {
    return (
      <nav className="lf-tabbar" aria-label="Primary shortcuts">
        {tabBarItems().map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className="lf-tabbar-item">
            <item.icon size={20} strokeWidth={1.8} aria-hidden="true" />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
    );
  }

  return (
    <>
      <nav className="lf-tabbar" aria-label="Primary shortcuts">
        {tabBarItemsV2().map((item) =>
          item.action ? (
            <button
              key={item.to}
              type="button"
              className="lf-tabbar-item lf-tabbar-add"
              onClick={() => setAdding(true)}
              aria-haspopup="dialog"
              aria-expanded={adding}
            >
              <item.icon size={22} strokeWidth={2.2} aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          ) : (
            <NavLink key={item.to} to={item.to} end={item.end} className="lf-tabbar-item">
              <item.icon size={20} strokeWidth={1.8} aria-hidden="true" />
              <span>{item.label}</span>
            </NavLink>
          ),
        )}
      </nav>

      <AddActionSheet open={adding} onClose={() => setAdding(false)} />
    </>
  );
}
