import { useId, type ReactNode } from "react";
import type { SceneProps, SceneTone } from "./ClayScene";

/**
 * The third illustration language: line art, and about **money in transit**.
 *
 * The three sets make three different arguments, which is why all three are
 * worth having rather than being one drawing in three skins:
 *
 * * **Clay** draws the *thing* — a vault, a shield. It says: this is solid.
 * * **Doodle** draws *somebody doing something*. It says: this is human.
 * * **Motion** draws *money going somewhere*. It says: this is your money
 *   moving, and here is where it went.
 *
 * The third is the closest to what the product is actually about. A ledger is
 * a record of movement, and every screen in this application is answering some
 * version of "where did it go?".
 *
 * **What makes it read as this set.** Four things:
 *
 * 1. **A dashed trail.** Every scene has a visible path connecting where money
 *    was to where it went. The trail is the subject; the person is the reason
 *    it matters.
 * 2. **Two weights of line.** A heavy contour for the subject, a light one for
 *    everything the subject is reacting to. The reference material does this
 *    and it is what stops flat line art reading as a wireframe.
 * 3. **Flat fills that sit inside the line**, unlike the doodle set's
 *    deliberately offset wash. This set is drawn by a machine and does not
 *    pretend otherwise.
 * 4. **Marks around the subject** — ticks, dots, a scribble — carrying the
 *    feeling the face is too small to carry at spot size.
 *
 * ## Motion, and the reduced-motion contract
 *
 * Every animation here is **cyclical, with 0% and 100% identical**. That is not
 * a style choice, it is what makes the set safe:
 *
 * `base.css` neutralises motion globally by forcing `animation-duration` to
 * 0.01ms and `animation-iteration-count` to 1 — which lands every animation on
 * its *end* state. A "money flies away" animation written as a one-way trip
 * would therefore leave a reduced-motion user with an empty frame: the notes
 * would all be at their off-screen destination. Because every keyframe here
 * returns to its origin, the end state and the resting composition are the same
 * drawing, and the illustration is complete either way.
 *
 * `illustration.css` additionally sets `animation: none` on these classes under
 * reduced motion, because an infinite loop with a near-zero duration still
 * schedules work on every frame.
 */

const TONE_TOKEN: Record<SceneTone, string> = {
  accent: "var(--lf-action-primary)",
  positive: "var(--lf-status-success)",
  caution: "var(--lf-status-warning)",
  neutral: "var(--lf-text-tertiary)",
};

export type MotionProps = SceneProps;

export function useMotionIds() {
  const base = useId().replace(/:/g, "");
  return { wash: `lf-motion-wash-${base}`, clip: `lf-motion-clip-${base}` };
}

export type MotionIds = ReturnType<typeof useMotionIds>;

export function MotionScene({
  title,
  tone = "accent",
  className,
  ids,
  children,
  marks = true,
}: MotionProps & {
  ids: MotionIds;
  children: ReactNode;
  /** The small marks around the subject. Off for the densest scenes. */
  marks?: boolean;
}) {
  const hue = TONE_TOKEN[tone];

  return (
    <svg
      viewBox="0 0 200 170"
      className={["lf-illus", "lf-illus--motion", className].filter(Boolean).join(" ")}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      <defs>
        <radialGradient id={ids.wash} cx="0.5" cy="0.4" r="0.75">
          <stop offset="0%" stopColor={hue} stopOpacity="0.12" />
          <stop offset="100%" stopColor={hue} stopOpacity="0" />
        </radialGradient>
      </defs>

      <rect x="0" y="0" width="200" height="170" fill={`url(#${ids.wash})`} />

      {marks && (
        <g
          className="lf-motion-marks"
          stroke="var(--lf-text-tertiary)"
          strokeWidth="2.2"
          strokeLinecap="round"
          fill="none"
          opacity="0.5"
        >
          {/* Clustered near the subject's head, where a reaction belongs.
              Scattered to the frame corners they read as dust on the lens. */}
          <path d="M22 62l7-5M26 48v-8M14 76h-7" />
          <circle cx="16" cy="52" r="1.8" fill="var(--lf-text-tertiary)" stroke="none" />
        </g>
      )}

      {/* The ground: a single flat line. The clay set casts a shadow and the
          doodle set scribbles; this one draws exactly one stroke, because the
          language is line art and anything softer would belong to another set. */}
      <path
        d="M52 145h96"
        stroke="var(--lf-text-tertiary)"
        strokeWidth="2"
        strokeLinecap="round"
        opacity="0.35"
      />

      <g fill="none" stroke="var(--lf-text-primary)" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round">
        {children}
      </g>
    </svg>
  );
}

/**
 * The dashed path money travels along.
 *
 * Animated by `stroke-dashoffset`, which is the one property that can make a
 * line look like it is *flowing* without moving the line itself — so the trail
 * reads as direction of travel while staying exactly where it was drawn.
 */
export function Trail({ d, tone = "accent" }: { d: string; tone?: SceneTone }) {
  return (
    <path
      className="lf-motion-trail"
      d={d}
      stroke={TONE_TOKEN[tone]}
      strokeWidth="2"
      strokeDasharray="5 5"
      opacity="0.7"
      fill="none"
    />
  );
}

/**
 * A banknote, travelling.
 *
 * `delay` staggers a group so they do not move in lockstep, which is the
 * difference between money escaping and a carousel.
 */
export function Note({
  x,
  y,
  scale = 1,
  delay = 0,
  tilt = 0,
}: {
  x: number;
  y: number;
  scale?: number;
  delay?: number;
  tilt?: number;
}) {
  // Two nested groups, and the nesting is load-bearing.
  //
  // A CSS `transform` from an animation **replaces** the `transform`
  // presentation attribute rather than composing with it. With both on one
  // element every note snapped to the SVG origin the moment the animation
  // applied, and the whole set rendered with its money piled invisibly in the
  // top-left corner. Position on the outer group, animate the inner one.
  return (
    <g transform={`translate(${x} ${y}) scale(${scale}) rotate(${tilt})`}>
      <g className="lf-motion-travel" style={{ animationDelay: `${delay}s` }}>
        <rect
          x="-14"
          y="-9"
          width="28"
          height="18"
          rx="2"
          fill="var(--lf-status-success)"
          fillOpacity="0.55"
        />
        <circle cx="0" cy="0" r="4" />
        <path d="M-9 -5h2M9 5h-2" strokeWidth="2.4" />
      </g>
    </g>
  );
}

/** A coin, travelling. Smaller and faster than a note. */
export function Coin({ x, y, delay = 0 }: { x: number; y: number; delay?: number }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <g className="lf-motion-travel" style={{ animationDelay: `${delay}s` }}>
        <circle cx="0" cy="0" r="6" fill="var(--lf-status-warning)" fillOpacity="0.6" />
        <path d="M0 -3v6" strokeWidth="2.4" />
      </g>
    </g>
  );
}

/**
 * The person.
 *
 * More drawn than the doodle set's stick figure and still faceless — for the
 * same reason: drawing a face means deciding whose face, and on a product used
 * in a hundred countries the honest answer is that we do not know. Posture and
 * the marks around the head carry the feeling instead.
 */
export function Figure({
  x = 0,
  y = 0,
  scale = 1,
  flip = false,
  arms = "down",
}: {
  x?: number;
  y?: number;
  scale?: number;
  flip?: boolean;
  /** What the arms are doing — the whole of the character. */
  arms?: "down" | "up" | "out" | "hold" | "point";
}) {
  // Arms hang from the shoulder line at y=-24, not from the waist. The first
  // version attached them at the origin, which put the elbows below the hips.
  const armPaths: Record<string, string> = {
    down: "M-11 -24l-7 20M11 -24l7 20",
    up: "M-11 -24l-10-15M11 -24l10-15",
    out: "M-11 -24l-16 5M11 -24l16 5",
    hold: "M-11 -25l-9 9 9 6M11 -25l9 9-9 6",
    point: "M-11 -24l-7 20M11 -26l17-8",
  };

  return (
    <g transform={`translate(${x} ${y}) scale(${flip ? -scale : scale} ${scale})`}>
      {/* Origin is the hip, so a scene positions the figure by where it stands
          rather than by where its head happens to land.

          The torso stops at y=-30 and the head starts at y=-44. The first
          version overlapped them — the torso's fill ran up across the lower
          face and the neck line straight through the skull, which rendered as
          a masked blob rather than a person. Keeping the two shapes apart with
          a real neck between them is the whole fix. */}
      <path d="M-4 0l-7 30M4 0l7 30" />
      <path
        d="M-11 -30c0-5 22-5 22 0v30h-22z"
        fill="var(--lf-action-primary)"
        fillOpacity="0.28"
      />
      <path d={armPaths[arms]} />
      <path d="M0 -34v4" />
      <circle cx="0" cy="-44" r="10" fill="var(--lf-bg-surface)" />
      {/* Hair as a cap over the top of the skull, drawn after it so the fill
          reads as hair rather than as a hole in the head. */}
      <path
        d="M-10 -45a10 10 0 0120 0c-3-4-6-5-10-5s-7 1-10 5z"
        fill="var(--lf-text-primary)"
      />
    </g>
  );
}

/** The scribble of frustration above a head. One mark, used sparingly. */
export function Scribble({ x, y }: { x: number; y: number }) {
  return (
    <g transform={`translate(${x} ${y})`} opacity="0.7">
      <g className="lf-motion-pulse">
        <path
          d="M-9 2c-6-5-2-11 4-9s7 8 1 10-11-3-8-9 12-6 15 0"
          strokeWidth="2.4"
          stroke="var(--lf-text-secondary)"
        />
      </g>
    </g>
  );
}
