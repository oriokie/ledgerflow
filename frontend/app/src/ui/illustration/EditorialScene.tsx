import type { SceneProps } from "./ClayScene";

const EDITORIAL_ASSET_NAMES = [
  "secure",
  "welcome",
  "insight",
  "no-data",
  "vault",
  "growth",
  "compass",
  "success",
  "envelope",
  "cycle",
  "path",
  "waiting",
  "holdings",
  "portfolio",
  "horizon",
  "search",
  "conversation",
  "together",
  "adjust",
  "signal",
  "steps",
  "lost",
  "offline",
  "maintenance",
  "broken",
] as const;

export type EditorialAssetName = (typeof EDITORIAL_ASSET_NAMES)[number];

/**
 * The people-first editorial set.
 *
 * These are high-resolution generated assets rather than token-painted SVGs,
 * so the semantic registry owns their filenames. Callers still ask for what an
 * image means; they never depend on the person or object currently drawn.
 */
export function EditorialScene({
  asset,
  title,
}: SceneProps & { asset: EditorialAssetName }) {
  return (
    <span className="lf-illus lf-illus--editorial">
      <img
        className="lf-editorial-image lf-editorial-image--light"
        src={`/illustrations/editorial/${asset}.webp`}
        alt={title ?? ""}
        aria-hidden={title ? undefined : true}
        draggable={false}
        decoding="async"
      />
      <img
        className="lf-editorial-image lf-editorial-image--dark"
        src={`/illustrations/editorial/${asset}-dark.webp`}
        alt=""
        aria-hidden="true"
        draggable={false}
        decoding="async"
      />
    </span>
  );
}
