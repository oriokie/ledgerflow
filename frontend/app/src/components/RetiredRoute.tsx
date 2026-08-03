import type { ReactElement } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { RETIRED_PATHS } from "./shell/navConfigV2";
import { useFlag } from "../lib/featureFlags";

/**
 * A path the new IA retires, serving whichever version the user is on.
 *
 * With the flag off this renders exactly what it always did. With it on, the
 * path 301s in spirit — `<Navigate replace>` — to its new home with the right
 * tab preselected, so `/bills` lands on `/plan?tab=bills` rather than on a
 * generic Plan page where the user has to find bills again.
 *
 * Two details that matter:
 *
 * - `replace`, so the retired URL doesn't sit in the back stack. Without it,
 *   pressing Back from `/plan?tab=bills` returns to `/bills`, which
 *   immediately forwards again — the classic redirect trap where Back appears
 *   broken.
 * - The original `search` and `hash` are preserved and merged, so a deep link
 *   like `/transactions?category=abc` keeps its filter when it becomes
 *   `/activity?category=abc`.
 */
export function RetiredRoute({ path, legacy }: { path: string; legacy: ReactElement }) {
  const [navV2] = useFlag("navV2");
  const location = useLocation();

  if (!navV2) return legacy;

  const target = RETIRED_PATHS[path];
  if (!target) return legacy;

  const [pathname, ownSearch = ""] = target.split("?");
  const incoming = new URLSearchParams(location.search);
  const merged = new URLSearchParams(ownSearch);
  // The incoming query wins on collision: an explicit `?tab=` the user typed
  // is a stronger signal than the default this table supplies.
  incoming.forEach((value, key) => merged.set(key, value));

  const search = merged.toString();
  return <Navigate to={`${pathname}${search ? `?${search}` : ""}${location.hash}`} replace />;
}
