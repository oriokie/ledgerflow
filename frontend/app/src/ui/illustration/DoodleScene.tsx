import { useId, type ReactNode } from "react";

/**
 * The second illustration language: hand-drawn, and about people.
 *
 * Where the clay set is about *things being kept safe* — a vault, a shield, a
 * ledger — this one is about somebody doing something. That is the actual
 * difference between the two, and it is why both are worth having rather than
 * being the same drawings in a different skin: a product can want to feel
 * substantial, or it can want to feel human, and those are different weeks.
 *
 * **What makes it read as hand-drawn.** Four things, and none of them is a
 * texture filter:
 *
 * 1. **Open strokes, not filled masses.** Everything is drawn with a line of
 *    consistent weight and round caps. Fills exist, but they sit *behind* the
 *    line as loose colour, the way a marker sits behind ink.
 * 2. **The fill is offset from the line.** Colour that does not quite line up
 *    with its outline is the single most legible signal of a human hand; a
 *    perfectly registered fill reads as vector art immediately.
 * 3. **Nothing is quite straight or level.** Every element carries a small
 *    rotation, and no two are the same.
 * 4. **A visible construction mark** — a stray tick, an underline, a couple of
 *    motion lines — the marks someone leaves behind when drawing quickly.
 *
 * Everything is still built from design tokens, so it recolours in dark mode
 * and is gated by the same contrast script. And like the clay set it is
 * `aria-hidden` unless given a `title`.
 */
export type DoodleTone = "accent" | "positive" | "caution" | "neutral";

export interface DoodleProps {
  title?: string;
  tone?: DoodleTone;
  className?: string;
}

const TONE_TOKEN: Record<DoodleTone, string> = {
  accent: "var(--lf-action-primary)",
  positive: "var(--lf-status-success)",
  caution: "var(--lf-status-warning)",
  neutral: "var(--lf-text-tertiary)",
};

export function useDoodleIds() {
  const base = useId().replace(/:/g, "");
  return { wash: `lf-doodle-wash-${base}`, blob: `lf-doodle-blob-${base}` };
}

export type DoodleIds = ReturnType<typeof useDoodleIds>;

export function DoodleScene({
  title,
  tone = "accent",
  className,
  ids,
  children,
  chips = true,
}: DoodleProps & { ids: DoodleIds; children: ReactNode; chips?: boolean }) {
  const hue = TONE_TOKEN[tone];

  return (
    <svg
      viewBox="0 0 200 170"
      className={["lf-illus", "lf-illus--doodle", className].filter(Boolean).join(" ")}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      <defs>
        <radialGradient id={ids.wash} cx="0.5" cy="0.35" r="0.75">
          <stop offset="0%" stopColor={hue} stopOpacity="0.14" />
          <stop offset="100%" stopColor={hue} stopOpacity="0" />
        </radialGradient>
      </defs>

      <rect x="0" y="0" width="200" height="170" fill={`url(#${ids.wash})`} />

      {chips && (
        <g className="lf-illus-chips" stroke={hue} strokeWidth="2.4" strokeLinecap="round" fill="none" opacity="0.4">
          <path d="M30 34l7-7M34 30h-9" />
          <path d="M168 44c3-4 7-4 10 0" />
          <path d="M164 124l6 6M170 124l-6 6" />
        </g>
      )}

      {/* The ground: a scribbled line rather than a shadow, because a soft
          shadow under a line drawing looks like two illustrations at once. */}
      <path
        d="M56 141c14-4 30-5 44-5s31 1 45 5"
        stroke="var(--lf-text-tertiary)"
        strokeWidth="2.6"
        strokeLinecap="round"
        fill="none"
        opacity="0.45"
      />

      <g
        fill="none"
        stroke="var(--lf-text-primary)"
        strokeWidth="3.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {children}
      </g>
    </svg>
  );
}

/**
 * Loose colour behind the line.
 *
 * Offset by a couple of units and slightly rotated on purpose — a fill that
 * registers perfectly with its outline is the thing that makes hand-drawn
 * artwork look like it was made by a machine imitating one.
 */
export function Wash({
  tone = "accent",
  children,
  dx = 3,
  dy = 3,
  rotate = -1.5,
  opacity = 0.3,
}: {
  tone?: DoodleTone;
  children: ReactNode;
  dx?: number;
  dy?: number;
  rotate?: number;
  opacity?: number;
}) {
  return (
    <g
      fill={TONE_TOKEN[tone]}
      stroke="none"
      opacity={opacity}
      transform={`translate(${dx} ${dy}) rotate(${rotate} 100 85)`}
    >
      {children}
    </g>
  );
}

/**
 * A person, drawn once and reused at different angles.
 *
 * Deliberately faceless — no eyes or mouth. Drawing a face means deciding
 * whose face, and on a product used in a hundred countries the honest answer
 * is that we do not know. Posture, hair silhouette and clothing carry the
 * meaning: what someone is *doing* is the subject, not who they are.
 */
export function Figure({
  x = 0,
  y = 0,
  scale = 1,
  flip = false,
  tilt = 0,
  arms = "down",
  hair = "short",
  seated = false,
}: {
  x?: number;
  y?: number;
  scale?: number;
  flip?: boolean;
  tilt?: number;
  /** What the arms are doing — the whole of the character. */
  arms?: "down" | "up" | "point" | "hold" | "wave";
  hair?: "short" | "long" | "bun" | "curly";
  seated?: boolean;
}) {
  const armPaths: Record<string, string> = {
    down: "M-14 -2 Q-18 8 -12 20 M14 -2 Q18 8 12 20",
    up: "M-14 -4 Q-20 -14 -16 -28 M14 -4 Q20 -14 16 -28",
    point: "M-14 -2 Q-18 8 -12 20 M14 -6 Q22 -10 28 -18",
    hold: "M-14 -4 Q-20 2 -16 10 Q-8 14 0 8 M14 -4 Q20 2 16 10 Q8 14 0 8",
    wave: "M-14 -2 Q-18 8 -12 20 M14 -8 Q22 -14 20 -22 Q18 -28 24 -26",
  };

  const hairPaths: Record<string, string> = {
    short: "M-11 -24 Q0 -34 11 -24",
    long: "M-12 -24 Q0 -36 12 -24 Q10 -14 0 -12 Q-10 -14 -12 -24",
    bun: "M-10 -24 Q0 -34 10 -24 M6 -28a5 5 0 1 1-12 0",
    curly: "M-12 -22 Q-6 -32 0 -24 Q6 -32 12 -22 Q8 -14 0 -12 Q-8 -14 -12 -22",
  };

  const legs = seated
    ? "M-8 24 Q-8 30 -18 32 M8 24 Q8 30 18 32"
    : "M-7 24 Q-8 30 -9 36 M7 24 Q8 30 9 36";

  return (
    <g transform={`translate(${x} ${y}) scale(${flip ? -scale : scale} ${scale}) rotate(${tilt})`}>
      <path
        d="M-13 2 Q0 8 13 2 L11 24 Q0 30 -11 24 Z"
        fill="var(--lf-text-primary)"
        fillOpacity="0.14"
        stroke="none"
      />
      <path d="M-13 2 Q0 -4 13 2 L11 24 Q0 30 -11 24 Z" />
      <path d="M-10 17 Q0 21 10 17" strokeWidth="2.2" opacity="0.45" />
      <path d={legs} />
      <path d="M0 -10v6" strokeWidth="2.6" />
      <circle cx="0" cy="-20" r="10" />
      <path d={hairPaths[hair]} strokeWidth="3.2" />
      <path d={armPaths[arms]} />
    </g>
  );
}
