import type { ReactNode } from "react";
import { useIllustrationStyleSetting } from "../hooks/usePlatform";
import { ILLUSTRATION_STYLES, IllustrationStyleProvider, type IllustrationStyle } from "../ui/illustration";

function devIllustrationOverride(): IllustrationStyle | undefined {
  if (!import.meta.env.DEV) return undefined;
  const raw = new URLSearchParams(window.location.search).get("illus");
  return ILLUSTRATION_STYLES.includes(raw as IllustrationStyle)
    ? (raw as IllustrationStyle)
    : undefined;
}

/**
 * Reads the platform's illustration style once, near the root.
 *
 * Sits outside the router and outside auth, because the surfaces that most
 * need an illustration — the landing page, the login form, the offline screen
 * — are exactly the ones nobody is signed in for.
 *
 * While the request is in flight, and if it fails entirely, the provider falls
 * back to `clay`. That is the important behaviour: an unreachable settings
 * endpoint must degrade to *an* illustration set, never to blank surfaces. The
 * hook does not retry for the same reason.
 */
export function IllustrationStyleGate({ children }: { children: ReactNode }) {
  const { data } = useIllustrationStyleSetting();
  const override = devIllustrationOverride();
  return (
    <IllustrationStyleProvider style={override ?? data?.illustration_style}>
      {children}
    </IllustrationStyleProvider>
  );
}
