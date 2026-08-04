import { X } from "lucide-react";
import { NavLink } from "react-router-dom";
import { useRoutePrefetch } from "../../hooks/useRoutePrefetch";
import { usePinnedViews } from "../../lib/pinnedViews";
import { metricFor, useRailMetrics } from "../../hooks/useRailMetrics";
import { useFlag } from "../../lib/featureFlags";
import { useAuth } from "../../lib/AuthContext";
import { NAV_SECTIONS, RECEIPT_SCAN_PATH } from "./navConfig";
import { NAV_SECTIONS_V2, type NavItemV2 } from "./navConfigV2";

/**
 * The grouped nav links. Rendered identically in the desktop rail and the
 * mobile drawer; `onNavigate` lets the drawer close itself on selection.
 * Relies on NavLink's automatic aria-current="page" for the active style.
 *
 * Hovering or focusing a link warms that route's data (see useRoutePrefetch),
 * so by the time the click lands the destination usually has something real to
 * paint instead of a skeleton. Focus is included so keyboard users get the same
 * benefit as mouse users.
 */
export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const prefetch = useRoutePrefetch();
  const [navV2] = useFlag("navV2");
  const metrics = useRailMetrics(navV2);
  const { user } = useAuth();

  // Receipt scanning is opt-in (see UserProfile.show_receipt_scanner): most
  // people photograph a receipt from the transaction they are already
  // entering, so a permanent nav entry for it costs everyone else a line.
  // Filtering here rather than in the config keeps one list of routes and lets
  // the preference apply to whichever nav version is in play.
  const sections = (navV2 ? NAV_SECTIONS_V2 : NAV_SECTIONS)
    .map((section) => ({
      ...section,
      items: section.items.filter(
        (item) => item.to !== RECEIPT_SCAN_PATH || user?.show_receipt_scanner,
      ),
    }))
    .filter((section) => section.items.length > 0);

  return (
    <>
      {navV2 && <PinnedSection onNavigate={onNavigate} />}
      {sections.map((section) => (
        <div key={section.label} className="lf-rail-section">
          <p className="lf-rail-section-label">{section.label}</p>
          {section.items.map((item) => {
            // The two configs are different shapes; only V2 items carry a
            // metric, and `metrics` is empty unless the flag is on anyway.
            const metric = navV2 ? metricFor(item as NavItemV2, metrics) : undefined;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end ?? false}
                className="lf-nav-item"
                onClick={onNavigate}
                onPointerEnter={() => prefetch(item.to)}
                onFocus={() => prefetch(item.to)}
              >
                <item.icon className="lf-nav-icon" size={18} strokeWidth={1.8} aria-hidden="true" />
                <span className="lf-nav-label">{item.label}</span>
                {metric?.text && (
                  <>
                    {/* The glyph is for the eye; the sentence is for everyone
                        else. "Accounts 39.1k" read aloud is not a sentence. */}
                    <span className="lf-nav-metric" data-tone={metric.tone} aria-hidden="true">
                      {metric.text}
                    </span>
                    <span className="lf-visually-hidden">{metric.label ?? metric.text}</span>
                  </>
                )}
              </NavLink>
            );
          })}
        </div>
      ))}
    </>
  );
}

/**
 * User-pinned views, above the fixed destinations.
 *
 * Absent entirely when empty — an empty "Pinned" heading is a permanent
 * reminder of a feature you are not using, which is worse than no feature.
 */
function PinnedSection({ onNavigate }: { onNavigate?: () => void }) {
  const { pins, unpin } = usePinnedViews();
  if (pins.length === 0) return null;

  return (
    <div className="lf-rail-section">
      <p className="lf-rail-section-label">Pinned</p>
      {pins.map((pinned) => (
        <div key={pinned.id} className="lf-pin-row">
          <NavLink to={pinned.to} className="lf-nav-item lf-pin-link" onClick={onNavigate}>
            <span className="lf-nav-label">{pinned.label}</span>
          </NavLink>
          <button
            type="button"
            className="lf-pin-remove"
            onClick={() => unpin(pinned.to)}
            aria-label={`Unpin ${pinned.label}`}
          >
            <X size={14} strokeWidth={2} aria-hidden="true" />
          </button>
        </div>
      ))}
    </div>
  );
}

/** The brand lockup used at the top of the rail and drawer. */
export function BrandMark() {
  return (
    <>
      <svg className="lf-nav-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <rect x="2" y="3" width="16" height="14" rx="3" stroke="currentColor" strokeWidth="1.8" />
        <path d="M6 8h8M6 12h5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      LedgerFlow
    </>
  );
}
