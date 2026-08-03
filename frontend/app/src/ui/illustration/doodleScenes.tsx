import { DoodleScene, Figure, Wash, useDoodleIds, type DoodleProps } from "./DoodleScene";

/**
 * The doodle motifs.
 *
 * Every one has a person in it — that is the point of the set. Where the clay
 * language draws the *thing* (a vault, a shield), this one draws somebody
 * doing something with it, which is a different feeling for the same product.
 *
 * The same 200×170 viewBox and the same ground line as the clay set, so the two
 * are swappable in place without any layout moving.
 */

/** Someone standing with what they've built: the hero. */
export function DoodleVault(props: DoodleProps) {
  const ids = useDoodleIds();
  return (
    <DoodleScene {...props} ids={ids}>
      <Wash tone={props.tone}>
        <rect x="76" y="52" width="66" height="72" rx="12" />
      </Wash>
      <rect x="76" y="52" width="66" height="72" rx="12" />
      <circle cx="109" cy="88" r="14" />
      <path d="M109 74v-5M109 107v5M95 88h-5M128 88h5" />
      {/* Standing beside it, one hand raised — proud of the thing, not
          guarding it. */}
      <Figure x={52} y={100} scale={1} arms="wave" tilt={-2} />
    </DoodleScene>
  );
}

/** Someone charting a rise. */
export function DoodleGrowth(props: DoodleProps) {
  const ids = useDoodleIds();
  return (
    <DoodleScene {...props} ids={ids}>
      <Wash tone={props.tone} rotate={1}>
        <rect x="72" y="86" width="20" height="36" rx="5" />
        <rect x="100" y="66" width="20" height="56" rx="5" />
        <rect x="128" y="44" width="20" height="78" rx="5" />
      </Wash>
      <rect x="72" y="86" width="20" height="36" rx="5" transform="rotate(-1 82 104)" />
      <rect x="100" y="66" width="20" height="56" rx="5" transform="rotate(1 110 94)" />
      <rect x="128" y="44" width="20" height="78" rx="5" transform="rotate(-1 138 83)" />
      <path d="M74 40l14-10 12 8 22-18" strokeWidth="3" opacity="0.55" />
      <Figure x={48} y={102} arms="point" />
    </DoodleScene>
  );
}

/** Two people, one lock: the auth surface. */
export function DoodleShield(props: DoodleProps) {
  const ids = useDoodleIds();
  const shield = "M118 44c11 7 21 10 29 10v27c0 19-13 30-29 37-16-7-29-18-29-37V54c8 0 18-3 29-10z";
  return (
    <DoodleScene {...props} ids={ids}>
      <Wash tone={props.tone}>
        <path d={shield} />
      </Wash>
      <path d={shield} />
      <path d="M105 82l9 9 17-19" />
      <Figure x={50} y={104} arms="up" tilt={2} scale={0.94} />
    </DoodleScene>
  );
}

/** Someone reaching for a key. */
export function DoodleKey(props: DoodleProps) {
  const ids = useDoodleIds();
  return (
    <DoodleScene {...props} ids={ids}>
      <Wash tone={props.tone}>
        <circle cx="126" cy="72" r="22" />
        <rect x="120" y="90" width="12" height="34" rx="5" />
      </Wash>
      <circle cx="126" cy="72" r="22" />
      <circle cx="126" cy="72" r="8" />
      <path d="M126 94v30M126 108h12M126 118h9" />
      <Figure x={58} y={104} arms="point" />
    </DoodleScene>
  );
}

/** A letter, and someone waiting on it. */
export function DoodleEnvelope(props: DoodleProps) {
  const ids = useDoodleIds();
  return (
    <DoodleScene {...props} ids={ids}>
      <Wash tone={props.tone}>
        <rect x="74" y="54" width="82" height="58" rx="10" />
      </Wash>
      <rect x="74" y="54" width="82" height="58" rx="10" transform="rotate(-1.5 115 83)" />
      <path d="M79 62l31 24a9 9 0 0011 0l31-24" />
      <path d="M150 40c4-5 9-6 13-2" strokeWidth="2.6" opacity="0.5" />
      <Figure x={46} y={104} arms="up" />
    </DoodleScene>
  );
}

/** Someone setting off: welcome and onboarding. */
export function DoodleCompass(props: DoodleProps) {
  const ids = useDoodleIds();
  return (
    <DoodleScene {...props} ids={ids}>
      <Wash tone={props.tone}>
        <circle cx="124" cy="80" r="32" />
      </Wash>
      <circle cx="124" cy="80" r="32" />
      <path d="M138 66l-9 24-24 9 9-24z" />
      {/* Motion lines: the mark of drawing something in a hurry, and the
          cheapest way to say "going somewhere". */}
      <path d="M30 74h14M26 86h20M34 98h12" strokeWidth="2.6" opacity="0.5" />
      <Figure x={58} y={104} arms="point" tilt={-4} />
    </DoodleScene>
  );
}

/** Two people, done. */
export function DoodleSuccess(props: DoodleProps) {
  const ids = useDoodleIds();
  return (
    <DoodleScene {...props} tone={props.tone ?? "positive"} ids={ids}>
      <Wash tone={props.tone ?? "positive"}>
        <circle cx="128" cy="76" r="30" />
      </Wash>
      <circle cx="128" cy="76" r="30" />
      <path d="M115 77l10 11 20-24" />
      <Figure x={46} y={104} arms="up" tilt={-3} scale={0.92} />
      <Figure x={76} y={106} arms="up" tilt={3} scale={0.84} flip />
    </DoodleScene>
  );
}

/** An empty box and somebody looking into it. */
export function DoodleEmpty(props: DoodleProps) {
  const ids = useDoodleIds();
  return (
    <DoodleScene {...props} tone={props.tone ?? "neutral"} ids={ids}>
      <Wash tone={props.tone ?? "neutral"}>
        <rect x="86" y="80" width="72" height="42" rx="9" />
      </Wash>
      <path d="M86 88v25a9 9 0 009 9h54a9 9 0 009-9V88" />
      <path d="M80 74h84l-6 14H86z" />
      <path d="M122 88v10" strokeWidth="2.6" opacity="0.5" />
      <Figure x={48} y={104} arms="down" tilt={4} />
    </DoodleScene>
  );
}

/** Someone searching, finding nothing. */
export function DoodleSearch(props: DoodleProps) {
  const ids = useDoodleIds();
  return (
    <DoodleScene {...props} tone={props.tone ?? "neutral"} ids={ids}>
      <Wash tone={props.tone ?? "neutral"}>
        <circle cx="122" cy="70" r="26" />
      </Wash>
      <circle cx="122" cy="70" r="26" />
      <path d="M141 89l16 17" />
      <Figure x={54} y={104} arms="hold" />
    </DoodleScene>
  );
}

/** Someone waving at a disconnected cloud. */
export function DoodleOffline(props: DoodleProps) {
  const ids = useDoodleIds();
  return (
    <DoodleScene {...props} tone={props.tone ?? "neutral"} ids={ids}>
      <Wash tone={props.tone ?? "neutral"}>
        <rect x="88" y="52" width="72" height="34" rx="17" />
      </Wash>
      <path d="M104 86a17 17 0 010-34 22 22 0 0142 4 15 15 0 01-2 30z" />
      <path d="M96 100l52 26M148 100l-52 26" stroke="var(--lf-status-warning)" strokeWidth="4" />
      <Figure x={48} y={106} arms="wave" tilt={-3} />
    </DoodleScene>
  );
}

/** Someone with a spanner. */
export function DoodleMaintenance(props: DoodleProps) {
  const ids = useDoodleIds();
  return (
    <DoodleScene {...props} tone={props.tone ?? "caution"} ids={ids}>
      <Wash tone={props.tone ?? "caution"}>
        <circle cx="126" cy="76" r="28" />
      </Wash>
      <circle cx="126" cy="76" r="28" />
      <circle cx="126" cy="76" r="11" />
      {[0, 60, 120].map((a) => (
        <path key={a} d="M126 48v-9M126 104v9" transform={`rotate(${a} 126 76)`} />
      ))}
      <Figure x={52} y={104} arms="hold" />
    </DoodleScene>
  );
}

/** Someone reading a map that runs out. */
export function DoodleLost(props: DoodleProps) {
  const ids = useDoodleIds();
  return (
    <DoodleScene {...props} tone={props.tone ?? "neutral"} ids={ids}>
      <Wash tone={props.tone ?? "neutral"}>
        <path d="M132 44c12 0 22 10 22 22 0 16-22 36-22 36s-22-20-22-36c0-12 10-22 22-22z" />
      </Wash>
      <path d="M132 44c12 0 22 10 22 22 0 16-22 36-22 36s-22-20-22-36c0-12 10-22 22-22z" />
      <circle cx="132" cy="66" r="8" />
      <path d="M52 122h8M70 118h8M88 112h8" strokeWidth="2.8" opacity="0.5" />
      <Figure x={54} y={104} arms="down" tilt={3} />
    </DoodleScene>
  );
}

/** Someone beside a toppled stack. */
export function DoodleBroken(props: DoodleProps) {
  const ids = useDoodleIds();
  return (
    <DoodleScene {...props} tone={props.tone ?? "caution"} ids={ids}>
      <Wash tone={props.tone ?? "caution"}>
        <rect x="88" y="48" width="70" height="26" rx="8" />
      </Wash>
      <rect x="88" y="48" width="70" height="26" rx="8" transform="rotate(-2 123 61)" />
      <rect x="92" y="84" width="30" height="26" rx="7" transform="rotate(-11 92 84)" />
      <rect x="130" y="86" width="30" height="26" rx="7" transform="rotate(9 130 86)" />
      <Figure x={50} y={104} arms="up" tilt={-4} />
    </DoodleScene>
  );
}

/** Someone having an idea. */
export function DoodleInsight(props: DoodleProps) {
  const ids = useDoodleIds();
  return (
    <DoodleScene {...props} ids={ids}>
      <Wash tone={props.tone}>
        <circle cx="126" cy="66" r="24" />
      </Wash>
      <path d="M126 42a24 24 0 0114 43v9h-28v-9a24 24 0 0114-43z" />
      <path d="M114 102h24M117 110h18" />
      <path d="M126 26v-8M154 40l7-6M98 40l-7-6" strokeWidth="2.8" opacity="0.6" />
      <Figure x={52} y={104} arms="up" tilt={-2} />
    </DoodleScene>
  );
}
