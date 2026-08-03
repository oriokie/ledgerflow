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
  VaultScene,
} from "./scenes";
import {
  DoodleBroken,
  DoodleCompass,
  DoodleEmpty,
  DoodleEnvelope,
  DoodleGrowth,
  DoodleInsight,
  DoodleKey,
  DoodleLost,
  DoodleMaintenance,
  DoodleOffline,
  DoodleSearch,
  DoodleShield,
  DoodleSuccess,
  DoodleVault,
} from "./doodleScenes";
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
  MotionVault,
} from "./motionScenes";

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
} as const;

export type IllustrationName = keyof typeof CLAY;

/** Same keys, by construction — `Record<IllustrationName, …>` is the guard. */
const DOODLE: Record<IllustrationName, (props: SceneProps) => ReactNode> = {
  vault: DoodleVault,
  growth: DoodleGrowth,
  secure: DoodleShield,
  recover: DoodleKey,
  verify: DoodleEnvelope,
  welcome: DoodleCompass,
  success: DoodleSuccess,
  "no-data": DoodleEmpty,
  "no-results": DoodleSearch,
  offline: DoodleOffline,
  maintenance: DoodleMaintenance,
  "not-found": DoodleLost,
  error: DoodleBroken,
  insight: DoodleInsight,
};

/** Same keys again — the `Record<IllustrationName, …>` is what enforces it. */
const MOTION: Record<IllustrationName, (props: SceneProps) => ReactNode> = {
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
};

/** Every registry, keyed by style — so adding a fourth set is one entry here
 * rather than another branch at the render site. */
const SETS: Record<IllustrationStyle, Record<IllustrationName, (props: SceneProps) => ReactNode>> = {
  clay: CLAY,
  doodle: DOODLE,
  motion: MOTION,
};

export const ILLUSTRATION_STYLES = ["clay", "doodle", "motion"] as const;
export type IllustrationStyle = (typeof ILLUSTRATION_STYLES)[number];

export const ILLUSTRATION_NAMES = Object.keys(CLAY) as IllustrationName[];

/**
 * The active style.
 *
 * A context with a `clay` default rather than a hook that fetches: the setting
 * is platform-wide and read once near the root, and an illustration that had
 * to wait on a request would flash empty on every screen it appears on —
 * including the login form, which is the first thing anyone sees.
 */
const StyleContext = createContext<IllustrationStyle>("clay");

export function IllustrationStyleProvider({
  style,
  children,
}: {
  style: IllustrationStyle | undefined;
  children: ReactNode;
}) {
  return <StyleContext.Provider value={style ?? "clay"}>{children}</StyleContext.Provider>;
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
  const Scene = SETS[resolved][name];

  return (
    <div
      className={["lf-illus-frame", className].filter(Boolean).join(" ")}
      data-size={size}
      data-style={resolved}
      data-animate={animate ? "true" : undefined}
    >
      <Scene {...scene} />
    </div>
  );
}

export type { SceneProps } from "./ClayScene";
