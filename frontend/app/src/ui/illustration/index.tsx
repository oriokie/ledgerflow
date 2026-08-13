import { createContext, useContext, type ReactNode } from "react";
import type { SceneProps } from "./ClayScene";
import {
  BrokenScene,
  CompassScene,
  EmptyTrayScene,
  EnvelopeScene,
  GrowthScene,
  InsightScene,
  KeyScene,
  LostScene,
  MaintenanceScene,
  OfflineScene,
  SearchScene,
  ShieldScene,
  SuccessScene,
  TogetherScene,
  VaultScene,
} from "./scenes";
import {
  MotionBroken,
  MotionCompass,
  MotionEmpty,
  MotionEnvelope,
  MotionGrowth,
  MotionInsight,
  MotionKey,
  MotionLost,
  MotionMaintenance,
  MotionOffline,
  MotionSearch,
  MotionShield,
  MotionSuccess,
  MotionTogether,
  MotionVault,
} from "./motionScenes";
import {
  EditorialScene,
  type EditorialAssetName,
} from "./EditorialScene";

export const ILLUSTRATION_STYLES = ["clay", "doodle", "motion"] as const;
export type IllustrationStyle = (typeof ILLUSTRATION_STYLES)[number];

export const ILLUSTRATION_NAMES = [
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
  // Compatibility names retained for existing callers and status routes.
  "recover",
  "verify",
  "no-results",
  "not-found",
  "error",
] as const;

export type IllustrationName = (typeof ILLUSTRATION_NAMES)[number];

/**
 * Illustrations are addressed by **what they mean**, never by what they show.
 *
 * `<Illustration name="offline" />` survives someone redrawing the motif — and
 * survives the whole set being swapped for another, which is exactly what the
 * style switch does. A name like `broken-antenna` would not.
 *
 * Both sets implement the same registry, so switching style can never leave a
 * surface without an illustration: the type system requires every name in one
 * set to exist in the other.
 */
const CLAY = {
  vault: VaultScene,
  growth: GrowthScene,
  secure: ShieldScene,
  recover: KeyScene,
  verify: EnvelopeScene,
  welcome: CompassScene,
  success: SuccessScene,
  "no-data": EmptyTrayScene,
  "no-results": SearchScene,
  offline: OfflineScene,
  maintenance: MaintenanceScene,
  "not-found": LostScene,
  error: BrokenScene,
  insight: InsightScene,
  together: TogetherScene,
} as const;

const MOTION = {
  vault: MotionVault,
  growth: MotionGrowth,
  secure: MotionShield,
  recover: MotionKey,
  verify: MotionEnvelope,
  welcome: MotionCompass,
  success: MotionSuccess,
  "no-data": MotionEmpty,
  "no-results": MotionSearch,
  offline: MotionOffline,
  maintenance: MotionMaintenance,
  "not-found": MotionLost,
  error: MotionBroken,
  insight: MotionInsight,
  together: MotionTogether,
} as const;

const VECTOR_SETS = {
  clay: CLAY,
  motion: MOTION,
} satisfies Record<
  Exclude<IllustrationStyle, "doodle">,
  Partial<Record<IllustrationName, (props: SceneProps) => ReactNode>>
>;

const VECTOR_FALLBACKS: Record<IllustrationName, keyof typeof CLAY> = {
  secure: "secure",
  welcome: "welcome",
  insight: "insight",
  "no-data": "no-data",
  vault: "vault",
  growth: "growth",
  compass: "welcome",
  success: "success",
  envelope: "verify",
  cycle: "growth",
  path: "growth",
  waiting: "together",
  holdings: "vault",
  portfolio: "insight",
  horizon: "growth",
  search: "no-results",
  conversation: "together",
  together: "together",
  adjust: "insight",
  signal: "verify",
  steps: "growth",
  lost: "not-found",
  offline: "offline",
  maintenance: "maintenance",
  broken: "error",
  recover: "recover",
  verify: "verify",
  "no-results": "no-results",
  "not-found": "not-found",
  error: "error",
};

const EDITORIAL_ASSETS: Record<IllustrationName, EditorialAssetName> = {
  secure: "secure",
  welcome: "welcome",
  insight: "insight",
  "no-data": "no-data",
  vault: "vault",
  growth: "growth",
  compass: "compass",
  success: "success",
  envelope: "envelope",
  cycle: "cycle",
  path: "path",
  waiting: "waiting",
  holdings: "holdings",
  portfolio: "portfolio",
  horizon: "horizon",
  search: "search",
  conversation: "conversation",
  together: "together",
  adjust: "adjust",
  signal: "signal",
  steps: "steps",
  lost: "lost",
  offline: "offline",
  maintenance: "maintenance",
  broken: "broken",
  recover: "secure",
  verify: "envelope",
  "no-results": "search",
  "not-found": "lost",
  error: "broken",
};

/**
 * The active style.
 *
 * A context with a `clay` default rather than a hook that fetches: the setting
 * is platform-wide and read once near the root, and an illustration that had
 * to wait on a request would flash empty on every screen it appears on —
 * including the login form, which is the first thing anyone sees.
 */
const StyleContext = createContext<IllustrationStyle>("doodle");

export function IllustrationStyleProvider({
  style,
  children,
}: {
  style: IllustrationStyle | undefined;
  children: ReactNode;
}) {
  return <StyleContext.Provider value={style ?? "doodle"}>{children}</StyleContext.Provider>;
}

export function useIllustrationStyle(): IllustrationStyle {
  return useContext(StyleContext);
}

/**
 * Sizes, not pixel values.
 *
 * `hero` is the landing page. `panel` is a page that has nothing else on it.
 * `spot` is the size used inside the application: small enough that a data
 * screen stays a data screen.
 */
export type IllustrationSize = "hero" | "panel" | "spot";

export function Illustration({
  name,
  size = "panel",
  className,
  style,
  animate,
  ...scene
}: SceneProps & {
  name: IllustrationName;
  size?: IllustrationSize;
  /** Force a style, ignoring the platform setting. Only the console's own
   * preview uses this — everywhere else must follow the setting. */
  style?: IllustrationStyle;
  /**
   * Let the `motion` set animate at `spot` size.
   *
   * Spot illustrations sit inside data screens, where movement beside numbers
   * someone is reading is exactly what the illustration brief rules out — so
   * they hold still by default. The one place that must override this is the
   * console's own style picker: an operator choosing an animated set has to be
   * able to see it move, or they are choosing blind.
   *
   * A prop rather than inferring it from `style` being passed, because "this
   * is a preview" and "this should animate" are two different facts and tying
   * them together is how the next caller gets a surprise.
   */
  animate?: boolean;
}) {
  const active = useIllustrationStyle();
  const resolved = style ?? active;
  let content: ReactNode;

  if (resolved === "doodle") {
    content = <EditorialScene asset={EDITORIAL_ASSETS[name]} {...scene} />;
  } else {
    const set: Partial<Record<IllustrationName, (props: SceneProps) => ReactNode>> =
      VECTOR_SETS[resolved];
    const Scene = set[name] ?? set[VECTOR_FALLBACKS[name]];
    content = Scene ? <Scene {...scene} /> : null;
  }

  return (
    <div
      className={["lf-illus-frame", className].filter(Boolean).join(" ")}
      data-size={size}
      data-style={resolved}
      data-animate={animate ? "true" : undefined}
    >
      {content}
    </div>
  );
}

export type { SceneProps } from "./ClayScene";
