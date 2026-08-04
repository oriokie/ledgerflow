/**
 * The commit this build came from, at the foot of the sidebar.
 *
 * Baked in at build time (see deploy/frontend.Dockerfile), not fetched: it
 * describes the bundle you are looking at. Asking the API would answer a
 * different question — which backend is running — and would keep answering it
 * confidently while a cached or half-deployed frontend sat in front of it,
 * which is precisely when someone goes looking for a version number.
 *
 * Shows "dev" outside a release build, because a blank space where a version
 * belongs reads as a bug in the version display rather than as "not built by
 * CI".
 */
export function AppVersion() {
  const release = import.meta.env.VITE_APP_RELEASE || "dev";
  // A 40-character SHA is unreadable and wraps the rail; seven is what git,
  // GitHub and every commit URL already use.
  const short = release === "dev" ? "dev" : release.slice(0, 7);

  return (
    <p className="lf-rail-version" title={release === "dev" ? "Local build" : release}>
      <span aria-hidden="true">v</span>
      <code>{short}</code>
    </p>
  );
}
