/**
 * The auth panel's product window: the same Overview capture the landing page
 * uses, so the graphic is the application rather than a drawing of it.
 *
 * Light/dark files swap with `data-theme`, not `prefers-color-scheme`, for the
 * same reason AppPreview does — a visitor who overrode their system theme
 * would otherwise get the wrong shot. The panel is `aria-hidden`, so the
 * images are decorative here; the landing preview keeps the descriptive alt.
 */
export function AuthProductShot({ dimmed = false }: { dimmed?: boolean }) {
  return (
    <div className={`lf-auth-shot${dimmed ? " lf-auth-shot--dimmed" : ""}`}>
      <div className="lf-auth-shot-chrome" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <img
        className="lf-auth-shot-img lf-auth-shot-img--light"
        src="/preview-dashboard-light.webp"
        alt=""
        width={948}
        height={412}
        decoding="async"
      />
      <img
        className="lf-auth-shot-img lf-auth-shot-img--dark"
        src="/preview-dashboard-dark.webp"
        alt=""
        width={948}
        height={412}
        decoding="async"
      />
    </div>
  );
}
