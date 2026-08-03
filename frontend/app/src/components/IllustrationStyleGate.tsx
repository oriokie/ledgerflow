import type { ReactNode } from "react";
import { useIllustrationStyleSetting } from "../hooks/usePlatform";
import { IllustrationStyleProvider } from "../ui/illustration";

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
  return (
    <IllustrationStyleProvider style={data?.illustration_style}>
      {children}
    </IllustrationStyleProvider>
  );
}
