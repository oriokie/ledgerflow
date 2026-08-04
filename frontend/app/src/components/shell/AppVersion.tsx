/**
 * The release at the foot of the sidebar.
 *
 * Two identifiers, two jobs. `VITE_APP_VERSION` is the human release from the
 * repo's VERSION file — the number a person quotes in a bug report. The commit
 * sha stays in the title attribute for whoever needs to know *exactly* which
 * build this is, because "1.0.0" answers "what do you have?" and the sha
 * answers "what am I debugging?".
 *
 * Both are baked in at build time (see deploy/frontend.Dockerfile), not
 * fetched: they describe the bundle you are looking at. Asking the API would
 * answer a different question — which backend is running — and would keep
 * answering it confidently while a stale or half-deployed frontend sat in
 * front of it, which is precisely when someone goes looking for a version.
 *
 * Shows "dev" outside a release build, because a blank space where a version
 * belongs reads as a bug in the version display rather than as "not built by
 * CI".
 */
export function AppVersion() {
  const version = import.meta.env.VITE_APP_VERSION || "";
  const release = import.meta.env.VITE_APP_RELEASE || "";
  const isRelease = Boolean(version) && release && release !== "dev";

  const label = isRelease ? `v${version}` : "dev";
  const detail = isRelease ? `v${version} — build ${release}` : "Local build";

  return (
    <p className="lf-rail-version" title={detail}>
      <code>{label}</code>
    </p>
  );
}
