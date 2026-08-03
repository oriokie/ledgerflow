import { useId, type ReactNode } from "react";

/**
 * The frame every illustration in the product is drawn inside.
 *
 * The brief asks that illustrations stay consistent in "style, lighting,
 * perspective, and colour palette". Those four things are not left to whoever
 * draws the next one: they live here, once. A scene supplies the backdrop, the
 * light, the material and the ground; a motif supplies only its silhouette. A
 * new illustration therefore cannot drift, because it never gets to decide any
 * of it.
 *
 * **What makes it read as clay.** Five things, applied to every form by the
 * shared paints below rather than per drawing:
 *
 * 1. A single light from the upper left, so highlights and shadows agree.
 * 2. A *warm* highlight and a *cool* core shadow — the thing that separates
 *    modelled material from a flat gradient.
 * 3. A rim light on the shaded edge, which is what stops a soft form reading
 *    as a blur.
 * 4. Ambient occlusion where forms meet, and a soft contact shadow beneath.
 * 5. Generous corner radii and no hairlines anywhere — clay has no edges.
 *
 * **Why vector rather than rendered 3D.** Every pixel is an SVG built from
 * design tokens. That is a deliberate trade: it costs photoreal texture, and
 * buys three things a rendered image cannot — it recolours itself in dark mode
 * with no second asset, its contrast is verifiable by the same script that
 * gates the rest of the palette, and it adds no network request to a page whose
 * whole argument is that it loads fast.
 *
 * Everything is `aria-hidden` unless the caller passes a `title`. An
 * illustration that repeats the heading beside it is noise to a screen reader.
 */
export type SceneTone = "accent" | "positive" | "caution" | "neutral";

export interface SceneProps {
  /** Named so the caller says what it means, not what it looks like. */
  title?: string;
  tone?: SceneTone;
  className?: string;
}

const TONE_TOKEN: Record<SceneTone, string> = {
  accent: "var(--lf-action-primary)",
  positive: "var(--lf-status-success)",
  caution: "var(--lf-status-warning)",
  neutral: "var(--lf-text-tertiary)",
};

/**
 * Ids must be unique per instance — two illustrations on one page sharing a
 * gradient id makes the second silently adopt the first one's fill, which is
 * the kind of bug that only shows up on the page that has both.
 */
export function useSceneIds() {
  const base = useId().replace(/:/g, "");
  return {
    body: `lf-clay-body-${base}`,
    bodySoft: `lf-clay-soft-${base}`,
    face: `lf-clay-face-${base}`,
    inset: `lf-clay-inset-${base}`,
    wash: `lf-clay-wash-${base}`,
    shade: `lf-clay-shade-${base}`,
    blur: `lf-clay-blur-${base}`,
    rim: `lf-clay-rim-${base}`,
  };
}

export type SceneIds = ReturnType<typeof useSceneIds>;

export function ClayScene({
  title,
  tone = "accent",
  className,
  ids,
  children,
  chips = true,
}: SceneProps & {
  ids: SceneIds;
  children: ReactNode;
  /** The drifting background elements. Off for spot illustrations. */
  chips?: boolean;
}) {
  const hue = TONE_TOKEN[tone];

  return (
    <svg
      viewBox="0 0 200 170"
      className={["lf-illus", className].filter(Boolean).join(" ")}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      <defs>
        {/* The material. Light from the upper left: a warm, near-white
            highlight at the top, the hue through the middle, and a cool
            deepened core shadow at the lower right. A single two-stop ramp
            reads as plastic; it is the third stop that reads as clay. */}
        <linearGradient id={ids.body} x1="0.15" y1="0.05" x2="0.85" y2="0.95">
          <stop offset="0%" stopColor="var(--lf-bg-surface)" stopOpacity="0.55" />
          <stop offset="34%" stopColor={hue} stopOpacity="0.95" />
          <stop offset="100%" stopColor="var(--lf-text-primary)" stopOpacity="0.55" />
        </linearGradient>

        {/* Secondary forms — the same material one step back, so a stacked
            shape reads as behind rather than as a different substance. */}
        <linearGradient id={ids.bodySoft} x1="0.15" y1="0.05" x2="0.85" y2="0.95">
          <stop offset="0%" stopColor="var(--lf-bg-surface)" stopOpacity="0.4" />
          <stop offset="40%" stopColor={hue} stopOpacity="0.55" />
          <stop offset="100%" stopColor="var(--lf-text-primary)" stopOpacity="0.35" />
        </linearGradient>

        {/* A lit face: panels, dials, anything catching the light head-on. */}
        <linearGradient id={ids.face} x1="0.2" y1="0" x2="0.8" y2="1">
          <stop offset="0%" stopColor="var(--lf-bg-surface)" stopOpacity="0.95" />
          <stop offset="100%" stopColor="var(--lf-bg-surface)" stopOpacity="0.62" />
        </linearGradient>

        {/* Recesses. Inverted so the shadow sits at the top edge, which is what
            makes a hole read as pressed *into* the form rather than sitting on
            top of it. */}
        <linearGradient id={ids.inset} x1="0.2" y1="0" x2="0.8" y2="1">
          <stop offset="0%" stopColor="var(--lf-text-primary)" stopOpacity="0.34" />
          <stop offset="100%" stopColor="var(--lf-text-primary)" stopOpacity="0.06" />
        </linearGradient>

        {/* Rim light along the shaded edge — the detail that stops a soft form
            reading as an out-of-focus blob. */}
        <linearGradient id={ids.rim} x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor="var(--lf-bg-surface)" stopOpacity="0.5" />
          <stop offset="55%" stopColor="var(--lf-bg-surface)" stopOpacity="0" />
        </linearGradient>

        <radialGradient id={ids.wash} cx="0.5" cy="0.32" r="0.78">
          <stop offset="0%" stopColor={hue} stopOpacity="0.18" />
          <stop offset="100%" stopColor={hue} stopOpacity="0" />
        </radialGradient>

        <radialGradient id={ids.shade} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor="var(--lf-text-primary)" stopOpacity="0.22" />
          <stop offset="65%" stopColor="var(--lf-text-primary)" stopOpacity="0.06" />
          <stop offset="100%" stopColor="var(--lf-text-primary)" stopOpacity="0" />
        </radialGradient>

        {/* Used for occlusion under overlapping forms. Kept small: a large blur
            radius is what makes soft shading look like fog. */}
        <filter id={ids.blur} x="-40%" y="-40%" width="180%" height="180%">
          <feGaussianBlur stdDeviation="4.5" />
        </filter>
      </defs>

      <rect x="0" y="0" width="200" height="170" fill={`url(#${ids.wash})`} />

      {chips && (
        <g className="lf-illus-chips">
          <rect x="26" y="24" width="20" height="20" rx="7" fill={hue} opacity="0.16" />
          <circle cx="172" cy="40" r="8" fill={hue} opacity="0.2" />
          <rect x="158" y="118" width="13" height="13" rx="4.5" fill={hue} opacity="0.13" />
          <circle cx="34" cy="112" r="5" fill={hue} opacity="0.14" />
        </g>
      )}

      {/* The contact shadow. Every motif sits on this, so nothing floats
          without weight and the perspective reads the same throughout. */}
      <ellipse cx="100" cy="142" rx="50" ry="10" fill={`url(#${ids.shade})`} />

      {children}
    </svg>
  );
}

/**
 * A soft shadow cast by one form onto another, for where shapes overlap.
 * Offset down-right because the light is upper-left — the offset is what
 * carries the direction, the blur only softens it.
 */
export function Occlusion({
  ids,
  children,
}: {
  ids: SceneIds;
  children: ReactNode;
}) {
  return (
    <g filter={`url(#${ids.blur})`} opacity="0.5" transform="translate(3 5)">
      {children}
    </g>
  );
}
