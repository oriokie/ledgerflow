import {
  Coin,
  Figure,
  MotionScene,
  Note,
  Scribble,
  Trail,
  useMotionIds,
  type MotionProps,
} from "./MotionScene";

/**
 * The motion motifs.
 *
 * Every one has a **trail** in it — that is the point of the set. Where clay
 * draws the thing and doodle draws somebody doing something, this one draws
 * money going somewhere, which is what a ledger is a record of.
 *
 * Same 200×170 viewBox and the same ground line as the other two sets, so all
 * three are swappable in place without any layout moving.
 */

/** Money arriving and being kept: the trail runs *inward*. */
export function MotionVault(props: MotionProps) {
  const ids = useMotionIds();
  return (
    <MotionScene {...props} ids={ids}>
      <Trail d="M186 40C150 46 152 78 122 82" tone={props.tone} />
      <rect x="74" y="60" width="60" height="62" rx="10" fill="var(--lf-action-primary)" fillOpacity="0.16" />
      <circle cx="104" cy="91" r="13" />
      <path d="M104 78v-4M104 104v4M91 91h-4M117 91h4" strokeWidth="2.4" />
      <Note x={168} y={38} scale={0.8} delay={0} tilt={-8} />
      <Figure x={44} y={115} arms="up" scale={0.9} />
    </MotionScene>
  );
}

/** A rising line, and someone pointing at it. */
export function MotionGrowth(props: MotionProps) {
  const ids = useMotionIds();
  return (
    <MotionScene {...props} ids={ids}>
      <rect x="82" y="94" width="18" height="28" rx="3" fill="var(--lf-action-primary)" fillOpacity="0.2" />
      <rect x="108" y="74" width="18" height="48" rx="3" fill="var(--lf-action-primary)" fillOpacity="0.28" />
      <rect x="134" y="50" width="18" height="72" rx="3" fill="var(--lf-action-primary)" fillOpacity="0.36" />
      <Trail d="M84 90C104 86 118 68 148 42" tone={props.tone} />
      <Coin x={160} y={36} delay={0.4} />
      <Note x={106} y={72} scale={0.6} delay={0.1} tilt={-10} />
      <Figure x={46} y={115} arms="point" scale={0.9} />
    </MotionScene>
  );
}

/** Money going in behind a shield: the auth surface. */
export function MotionShield(props: MotionProps) {
  const ids = useMotionIds();
  const shield = "M116 50c10 6 19 9 26 9v25c0 17-12 27-26 33-14-6-26-16-26-33V59c7 0 16-3 26-9z";
  return (
    <MotionScene {...props} ids={ids}>
      <Trail d="M182 46C154 52 152 74 130 80" tone={props.tone} />
      <path d={shield} fill="var(--lf-action-primary)" fillOpacity="0.18" />
      <path d="M104 86l8 8 16-18" strokeWidth="2.6" />
      <Note x={170} y={44} scale={0.72} delay={0.2} tilt={6} />
      <Figure x={46} y={115} arms="up" scale={0.88} />
    </MotionScene>
  );
}

/** A key on its way back to its owner. */
export function MotionKey(props: MotionProps) {
  const ids = useMotionIds();
  return (
    <MotionScene {...props} ids={ids}>
      <Trail d="M70 108C92 108 100 92 118 80" tone={props.tone} />
      <circle cx="128" cy="72" r="19" fill="var(--lf-action-primary)" fillOpacity="0.18" />
      <circle cx="128" cy="72" r="7" />
      <path d="M128 91v28M128 106h11M128 116h8" />
      <Coin x={96} y={98} delay={0.2} />
      <Figure x={48} y={115} arms="out" scale={0.9} />
    </MotionScene>
  );
}

/** A letter in flight. */
export function MotionEnvelope(props: MotionProps) {
  const ids = useMotionIds();
  return (
    <MotionScene {...props} ids={ids}>
      <Trail d="M60 116C88 116 96 84 122 74" tone={props.tone} />
      <g className="lf-motion-bob">
        <rect x="96" y="52" width="72" height="48" rx="6" fill="var(--lf-action-primary)" fillOpacity="0.16" />
        <path d="M100 57l28 21a8 8 0 009 0l28-21" strokeWidth="2.6" />
      </g>
      <Note x={92} y={96} scale={0.66} delay={0.35} tilt={-6} />
      <Figure x={48} y={115} arms="up" scale={0.9} />
    </MotionScene>
  );
}

/** Setting off: welcome and onboarding. */
export function MotionCompass(props: MotionProps) {
  const ids = useMotionIds();
  return (
    <MotionScene {...props} ids={ids}>
      <Trail d="M62 128C92 128 104 96 132 78" tone={props.tone} />
      <circle cx="132" cy="74" r="28" fill="var(--lf-action-primary)" fillOpacity="0.16" />
      <path d="M145 62l-8 21-21 8 8-21z" strokeWidth="2.6" />
      <Coin x={98} y={108} delay={0.15} />
      <Figure x={50} y={115} arms="point" scale={0.9} />
    </MotionScene>
  );
}

/** Done — and the money stayed. The one scene whose trail runs to the subject. */
export function MotionSuccess(props: MotionProps) {
  const ids = useMotionIds();
  const tone = props.tone ?? "positive";
  return (
    <MotionScene {...props} tone={tone} ids={ids}>
      <Trail d="M180 62C152 68 148 88 128 88" tone={tone} />
      <circle cx="120" cy="80" r="27" fill="var(--lf-status-success)" fillOpacity="0.2" />
      <path d="M108 81l9 10 18-22" strokeWidth="3" />
      <Coin x={168} y={58} delay={0.3} />
      <Figure x={48} y={115} arms="up" scale={0.9} />
    </MotionScene>
  );
}

/** An empty tray, and the trail that left it. */
export function MotionEmpty(props: MotionProps) {
  const ids = useMotionIds();
  const tone = props.tone ?? "neutral";
  return (
    <MotionScene {...props} tone={tone} ids={ids}>
      <Trail d="M118 92C142 88 156 66 182 54" tone={tone} />
      <path d="M84 82v26a8 8 0 008 8h44a8 8 0 008-8V82" fill="var(--lf-text-tertiary)" fillOpacity="0.12" />
      <path d="M78 70h72l-6 12H84z" />
      <Note x={172} y={50} scale={0.72} delay={0.1} tilt={-10} />
      <Figure x={46} y={115} arms="down" scale={0.9} />
    </MotionScene>
  );
}

/** Searching along a trail that ends in nothing. */
export function MotionSearch(props: MotionProps) {
  const ids = useMotionIds();
  const tone = props.tone ?? "neutral";
  return (
    <MotionScene {...props} tone={tone} ids={ids}>
      <Trail d="M64 118C92 118 100 88 112 74" tone={tone} />
      <circle cx="124" cy="68" r="24" fill="var(--lf-text-tertiary)" fillOpacity="0.12" />
      <path d="M141 86l16 17" strokeWidth="3" />
      <Coin x={92} y={100} delay={0.25} />
      <Figure x={48} y={115} arms="hold" scale={0.9} />
    </MotionScene>
  );
}

/** The trail breaks: nothing is reaching the other end. */
export function MotionOffline(props: MotionProps) {
  const ids = useMotionIds();
  const tone = props.tone ?? "neutral";
  return (
    <MotionScene {...props} tone={tone} ids={ids}>
      <Trail d="M64 116C86 116 94 98 104 88" tone={tone} />
      <path d="M110 88a16 16 0 010-32 21 21 0 0140 4 14 14 0 01-2 28z" fill="var(--lf-text-tertiary)" fillOpacity="0.12" />
      {/* The break is the message, so it is drawn in the warning colour and
          sits exactly where the trail stops rather than over the cloud. */}
      <path d="M96 100l20 20M116 100l-20 20" stroke="var(--lf-status-warning)" strokeWidth="3.4" />
      <Note x={84} y={104} scale={0.62} delay={0.1} tilt={4} />
      <Figure x={46} y={115} arms="out" scale={0.88} />
    </MotionScene>
  );
}

/** Work in progress on the line itself. */
export function MotionMaintenance(props: MotionProps) {
  const ids = useMotionIds();
  const tone = props.tone ?? "caution";
  return (
    <MotionScene {...props} tone={tone} ids={ids}>
      <Trail d="M62 120C90 120 100 96 112 84" tone={tone} />
      <g className="lf-motion-turn">
        <circle cx="128" cy="76" r="25" fill="var(--lf-status-warning)" fillOpacity="0.18" />
        <circle cx="128" cy="76" r="10" />
        {[0, 60, 120].map((a) => (
          <path key={a} d="M128 51v-8M128 101v8" transform={`rotate(${a} 128 76)`} strokeWidth="2.6" />
        ))}
      </g>
      <Coin x={90} y={104} delay={0.3} />
      <Figure x={48} y={115} arms="hold" scale={0.88} />
    </MotionScene>
  );
}

/** The trail runs off the edge: the page is not here. */
export function MotionLost(props: MotionProps) {
  const ids = useMotionIds();
  const tone = props.tone ?? "neutral";
  return (
    <MotionScene {...props} tone={tone} ids={ids}>
      <Trail d="M60 128C92 128 104 104 126 92" tone={tone} />
      <path
        d="M134 46c12 0 22 10 22 22 0 15-22 36-22 36s-22-21-22-36c0-12 10-22 22-22z"
        fill="var(--lf-text-tertiary)"
        fillOpacity="0.12"
      />
      <circle cx="134" cy="68" r="8" />
      <Coin x={92} y={112} delay={0.2} />
      <Figure x={48} y={115} arms="down" scale={0.88} />
      <Scribble x={26} y={56} />
    </MotionScene>
  );
}

/** The stack came apart mid-transfer. */
export function MotionBroken(props: MotionProps) {
  const ids = useMotionIds();
  const tone = props.tone ?? "caution";
  return (
    <MotionScene {...props} tone={tone} ids={ids}>
      <Trail d="M62 122C88 122 96 100 106 88" tone={tone} />
      <rect x="92" y="48" width="70" height="24" rx="5" fill="var(--lf-status-warning)" fillOpacity="0.16" />
      <rect x="94" y="84" width="30" height="24" rx="5" transform="rotate(-10 94 84)" />
      <rect x="132" y="86" width="30" height="24" rx="5" transform="rotate(9 132 86)" />
      <Note x={86} y={104} scale={0.62} delay={0.15} tilt={-8} />
      <Figure x={48} y={115} arms="up" scale={0.88} />
      <Scribble x={26} y={56} />
    </MotionScene>
  );
}

/** Following the trail back to what it means. */
export function MotionInsight(props: MotionProps) {
  const ids = useMotionIds();
  return (
    <MotionScene {...props} ids={ids}>
      <Trail d="M64 118C94 118 104 92 118 78" tone={props.tone} />
      <path d="M128 44a24 24 0 0114 43v9h-28v-9a24 24 0 0114-43z" fill="var(--lf-action-primary)" fillOpacity="0.2" />
      <path d="M116 104h24M119 112h18" strokeWidth="2.6" />
      <g className="lf-motion-pulse">
        <path d="M128 28v-8M156 42l7-6M100 42l-7-6" strokeWidth="2.6" opacity="0.7" />
      </g>
      <Coin x={92} y={102} delay={0.25} />
      <Figure x={48} y={115} arms="up" scale={0.88} />
    </MotionScene>
  );
}
