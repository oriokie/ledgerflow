import { ClayScene, Occlusion, useSceneIds, type SceneIds, type SceneProps } from "./ClayScene";

/**
 * The motifs.
 *
 * Each supplies a silhouette and nothing else — no gradients, no shadow, no
 * palette. Those come from `ClayScene`, which is why a new illustration cannot
 * drift from the others even if whoever adds it never reads this comment.
 *
 * The vocabulary is deliberately narrow: rounded masses, discs, and a single
 * accent hue against surface neutrals. Elegant rather than characterful — this
 * product is asking people to trust it with their money, and a mascot would be
 * working against that.
 *
 * The consistent build order for a form is: occlusion, mass, lit face, recess,
 * rim light. Following it is what makes two motifs drawn months apart look like
 * the same material.
 */

/** The rim light that runs along a form's shaded edge. */
function Rim({ ids, d }: { ids: SceneIds; d: string }) {
  return <path d={d} fill="none" stroke={`url(#${ids.rim})`} strokeWidth="2.5" strokeLinecap="round" />;
}

/** Money that is looked after: a vault door, catching light on its dial. */
export function VaultScene(props: SceneProps) {
  const ids = useSceneIds();
  return (
    <ClayScene {...props} ids={ids}>
      <Occlusion ids={ids}>
        <rect x="50" y="34" width="100" height="98" rx="26" fill="var(--lf-text-primary)" />
      </Occlusion>

      <rect x="50" y="34" width="100" height="98" rx="26" fill={`url(#${ids.body})`} />
      <rect x="62" y="46" width="76" height="74" rx="18" fill={`url(#${ids.face})`} />

      {/* The dial, pressed in and then raised — two layers is what gives it
          depth rather than looking like a printed circle. */}
      <circle cx="100" cy="83" r="24" fill={`url(#${ids.inset})`} />
      <circle cx="100" cy="83" r="18" fill={`url(#${ids.body})`} />
      <circle cx="100" cy="83" r="7.5" fill={`url(#${ids.face})`} />

      <rect x="96.5" y="57" width="7" height="13" rx="3.5" fill={`url(#${ids.face})`} />
      <rect x="96.5" y="96" width="7" height="13" rx="3.5" fill={`url(#${ids.face})`} />
      <rect x="74" y="79.5" width="13" height="7" rx="3.5" fill={`url(#${ids.face})`} />
      <rect x="113" y="79.5" width="13" height="7" rx="3.5" fill={`url(#${ids.face})`} />

      <Rim ids={ids} d="M150 96a26 26 0 01-26 36H76a26 26 0 01-26-26" />
    </ClayScene>
  );
}

/** Growth, as rising masses rather than a chart with invented numbers. */
export function GrowthScene(props: SceneProps) {
  const ids = useSceneIds();
  return (
    <ClayScene {...props} ids={ids}>
      <Occlusion ids={ids}>
        <rect x="48" y="88" width="30" height="44" rx="13" fill="var(--lf-text-primary)" />
        <rect x="85" y="62" width="30" height="70" rx="13" fill="var(--lf-text-primary)" />
        <rect x="122" y="38" width="30" height="94" rx="13" fill="var(--lf-text-primary)" />
      </Occlusion>

      <rect x="48" y="88" width="30" height="44" rx="13" fill={`url(#${ids.bodySoft})`} />
      <rect x="85" y="62" width="30" height="70" rx="13" fill={`url(#${ids.body})`} />
      <rect x="122" y="38" width="30" height="94" rx="13" fill={`url(#${ids.body})`} />

      {/* Lit top faces — the light is above, so the caps catch it. */}
      <rect x="52" y="92" width="22" height="9" rx="4.5" fill={`url(#${ids.face})`} opacity="0.75" />
      <rect x="89" y="66" width="22" height="9" rx="4.5" fill={`url(#${ids.face})`} opacity="0.8" />
      <rect x="126" y="42" width="22" height="9" rx="4.5" fill={`url(#${ids.face})`} opacity="0.85" />

      <circle cx="137" cy="24" r="10" fill="var(--lf-status-success)" />
      <circle cx="134" cy="21" r="3.4" fill="var(--lf-bg-surface)" opacity="0.6" />
      <Rim ids={ids} d="M152 106v13a13 13 0 01-13 13" />
    </ClayScene>
  );
}

/** A shield: the auth surface, and anything about safety. */
export function ShieldScene(props: SceneProps) {
  const ids = useSceneIds();
  const body = "M100 30c16 10 30 14 41 14v38c0 27-18 43-41 52-23-9-41-25-41-52V44c11 0 25-4 41-14z";
  return (
    <ClayScene {...props} ids={ids}>
      <Occlusion ids={ids}>
        <path d={body} fill="var(--lf-text-primary)" />
      </Occlusion>

      <path d={body} fill={`url(#${ids.body})`} />
      {/* The lit half, split down the axis of the light. */}
      <path
        d="M100 30c16 10 30 14 41 14v38c0 27-18 43-41 52V30z"
        fill="var(--lf-text-primary)"
        opacity="0.1"
      />
      <path
        d="M100 44c11 7 21 10 28 10v27c0 18-12 30-28 36V44z"
        fill={`url(#${ids.face})`}
        opacity="0.24"
      />

      <path
        d="M85 82l11 12 22-26"
        fill="none"
        stroke="var(--lf-bg-surface)"
        strokeWidth="8.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Rim ids={ids} d="M59 78v4c0 27 18 43 41 52" />
    </ClayScene>
  );
}

/** A key: password reset and recovery. */
export function KeyScene(props: SceneProps) {
  const ids = useSceneIds();
  return (
    <ClayScene {...props} ids={ids}>
      <Occlusion ids={ids}>
        <circle cx="76" cy="83" r="31" fill="var(--lf-text-primary)" />
        <rect x="100" y="72" width="56" height="22" rx="11" fill="var(--lf-text-primary)" />
      </Occlusion>

      <rect x="100" y="72" width="56" height="22" rx="11" fill={`url(#${ids.body})`} />
      <rect x="126" y="92" width="13" height="18" rx="6" fill={`url(#${ids.body})`} />
      <rect x="145" y="92" width="13" height="14" rx="6" fill={`url(#${ids.body})`} />

      <circle cx="76" cy="83" r="31" fill={`url(#${ids.body})`} />
      <circle cx="76" cy="83" r="14" fill={`url(#${ids.inset})`} />
      <circle cx="76" cy="83" r="10.5" fill="var(--lf-bg-app)" />
      {/* Highlight arc on the lit shoulder. */}
      <path
        d="M60 68a22 22 0 0114-6"
        fill="none"
        stroke="var(--lf-bg-surface)"
        strokeWidth="4"
        strokeLinecap="round"
        opacity="0.55"
      />
      <Rim ids={ids} d="M53 96a31 31 0 0023 18" />
    </ClayScene>
  );
}

/** An envelope: email verification and anything awaiting a click elsewhere. */
export function EnvelopeScene(props: SceneProps) {
  const ids = useSceneIds();
  return (
    <ClayScene {...props} ids={ids}>
      <Occlusion ids={ids}>
        <rect x="46" y="48" width="108" height="78" rx="20" fill="var(--lf-text-primary)" />
      </Occlusion>

      <rect x="46" y="48" width="108" height="78" rx="20" fill={`url(#${ids.body})`} />
      {/* The flap, as a lit plane folding away from the light. */}
      <path
        d="M46 68l45 33a15 15 0 0018 0l45-33v-2a18 18 0 00-18-18H64a18 18 0 00-18 18z"
        fill={`url(#${ids.face})`}
        opacity="0.5"
      />
      <path
        d="M52 62l41 30a12 12 0 0014 0l41-30"
        fill="none"
        stroke="var(--lf-bg-surface)"
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.9"
      />

      <circle cx="152" cy="50" r="15" fill="var(--lf-status-success)" />
      <circle cx="148" cy="46" r="4.5" fill="var(--lf-bg-surface)" opacity="0.5" />
      <path
        d="M146 50l4.5 4.5 8.5-9"
        fill="none"
        stroke="var(--lf-bg-surface)"
        strokeWidth="3.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Rim ids={ids} d="M46 106v2a18 18 0 0018 18h60" />
    </ClayScene>
  );
}

/** A compass: welcome, getting started, onboarding. */
export function CompassScene(props: SceneProps) {
  const ids = useSceneIds();
  return (
    <ClayScene {...props} ids={ids}>
      <Occlusion ids={ids}>
        <circle cx="100" cy="84" r="48" fill="var(--lf-text-primary)" />
      </Occlusion>

      <circle cx="100" cy="84" r="48" fill={`url(#${ids.body})`} />
      <circle cx="100" cy="84" r="37" fill={`url(#${ids.inset})`} />
      <circle cx="100" cy="84" r="33" fill={`url(#${ids.face})`} />

      {/* The needle: one lit half, one shaded, so it reads as a raised solid. */}
      <path d="M117 67l-11 28-28 11 11-28z" fill={`url(#${ids.body})`} />
      <path d="M117 67l-11 28-6-11z" fill="var(--lf-text-primary)" opacity="0.16" />
      <circle cx="100" cy="84" r="4.5" fill="var(--lf-bg-surface)" />
      <path
        d="M74 56a37 37 0 0119-10"
        fill="none"
        stroke="var(--lf-bg-surface)"
        strokeWidth="4"
        strokeLinecap="round"
        opacity="0.5"
      />
      <Rim ids={ids} d="M63 106a48 48 0 0028 25" />
    </ClayScene>
  );
}

/** A completed mark: success screens. */
export function SuccessScene(props: SceneProps) {
  const ids = useSceneIds();
  return (
    <ClayScene {...props} tone={props.tone ?? "positive"} ids={ids}>
      <Occlusion ids={ids}>
        <circle cx="100" cy="84" r="46" fill="var(--lf-text-primary)" />
      </Occlusion>

      <circle cx="100" cy="84" r="46" fill={`url(#${ids.body})`} />
      <circle cx="100" cy="84" r="36" fill="var(--lf-bg-surface)" opacity="0.12" />
      <path
        d="M78 85l15 16 30-35"
        fill="none"
        stroke="var(--lf-bg-surface)"
        strokeWidth="10"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M72 60a46 46 0 0122-16"
        fill="none"
        stroke="var(--lf-bg-surface)"
        strokeWidth="5"
        strokeLinecap="round"
        opacity="0.45"
      />
      <Rim ids={ids} d="M60 100a46 46 0 0030 29" />
    </ClayScene>
  );
}

/** An open, empty tray: no data yet. */
export function EmptyTrayScene(props: SceneProps) {
  const ids = useSceneIds();
  return (
    <ClayScene {...props} tone={props.tone ?? "neutral"} ids={ids}>
      <Occlusion ids={ids}>
        <rect x="48" y="76" width="104" height="52" rx="19" fill="var(--lf-text-primary)" />
      </Occlusion>

      {/* Sheets resting behind, drawn on the *lit* paint rather than the body
          one. At the neutral tone every form shares a hue, so without a real
          value difference the tray and its contents merge into one grey mass —
          which is exactly what the first version did. */}
      <rect x="74" y="40" width="52" height="26" rx="10" fill="var(--lf-bg-surface)" />
      <rect x="74" y="40" width="52" height="26" rx="10" fill={`url(#${ids.inset})`} opacity="0.35" />
      <rect x="64" y="54" width="72" height="30" rx="12" fill="var(--lf-bg-surface)" />
      <rect x="64" y="54" width="72" height="30" rx="12" fill={`url(#${ids.inset})`} opacity="0.2" />

      <rect x="48" y="76" width="104" height="52" rx="19" fill={`url(#${ids.body})`} />
      {/* The front lip, lit — it is what tells you the tray is open at the top. */}
      <rect x="58" y="82" width="84" height="16" rx="8" fill={`url(#${ids.inset})`} />
      <rect x="56" y="112" width="88" height="10" rx="5" fill={`url(#${ids.face})`} opacity="0.5" />
      <Rim ids={ids} d="M152 108a20 20 0 01-20 20H68a20 20 0 01-20-20" />
    </ClayScene>
  );
}

/** A lens over nothing: a search that matched no rows. */
export function SearchScene(props: SceneProps) {
  const ids = useSceneIds();
  return (
    <ClayScene {...props} tone={props.tone ?? "neutral"} ids={ids}>
      <Occlusion ids={ids}>
        <circle cx="90" cy="76" r="36" fill="var(--lf-text-primary)" />
        <rect x="112" y="100" width="40" height="17" rx="8.5" transform="rotate(42 112 100)" fill="var(--lf-text-primary)" />
      </Occlusion>

      <rect
        x="112"
        y="100"
        width="40"
        height="17"
        rx="8.5"
        transform="rotate(42 112 100)"
        fill={`url(#${ids.body})`}
      />
      <circle cx="90" cy="76" r="36" fill={`url(#${ids.body})`} />
      <circle cx="90" cy="76" r="25" fill={`url(#${ids.inset})`} />
      <circle cx="90" cy="76" r="21" fill="var(--lf-bg-app)" />
      <path
        d="M74 60a25 25 0 0114-7"
        fill="none"
        stroke="var(--lf-bg-surface)"
        strokeWidth="4"
        strokeLinecap="round"
        opacity="0.5"
      />
      <Rim ids={ids} d="M64 92a36 36 0 0026 20" />
    </ClayScene>
  );
}

/** A broken signal: offline. */
export function OfflineScene(props: SceneProps) {
  const ids = useSceneIds();
  return (
    <ClayScene {...props} tone={props.tone ?? "neutral"} ids={ids}>
      <Occlusion ids={ids}>
        <rect x="54" y="94" width="24" height="34" rx="10" fill="var(--lf-text-primary)" />
        <rect x="88" y="74" width="24" height="54" rx="10" fill="var(--lf-text-primary)" />
        <rect x="122" y="50" width="24" height="78" rx="10" fill="var(--lf-text-primary)" />
      </Occlusion>

      {/* Only the first bar is solid — the two that would mean "connected" are
          drawn as hollow wells, so the *absence* is the subject rather than a
          bar chart that happens to be pale. */}
      <rect x="54" y="94" width="24" height="34" rx="10" fill={`url(#${ids.body})`} />
      <rect x="58" y="98" width="16" height="9" rx="4.5" fill={`url(#${ids.face})`} opacity="0.7" />

      <rect x="88" y="74" width="24" height="54" rx="10" fill={`url(#${ids.inset})`} opacity="0.5" />
      <rect x="122" y="50" width="24" height="78" rx="10" fill={`url(#${ids.inset})`} opacity="0.35" />

      {/* The break: a raised bar in the warning hue, with its own shading so it
          belongs to the same material as everything else. */}
      <g transform="rotate(-34 100 88)">
        <rect x="52" y="82" width="96" height="14" rx="7" fill="var(--lf-status-warning)" />
        <rect x="56" y="85" width="88" height="4" rx="2" fill="var(--lf-bg-surface)" opacity="0.35" />
      </g>
      <Rim ids={ids} d="M78 110v8a10 10 0 01-10 10" />
    </ClayScene>
  );
}

/** Tools down: scheduled maintenance. */
export function MaintenanceScene(props: SceneProps) {
  const ids = useSceneIds();
  return (
    <ClayScene {...props} tone={props.tone ?? "caution"} ids={ids}>
      <Occlusion ids={ids}>
        <circle cx="100" cy="84" r="44" fill="var(--lf-text-primary)" />
      </Occlusion>

      <g>
        {[0, 45, 90, 135].map((angle) => (
          <rect
            key={angle}
            x="92"
            y="26"
            width="16"
            height="116"
            rx="8"
            fill={`url(#${ids.body})`}
            transform={`rotate(${angle} 100 84)`}
          />
        ))}
      </g>
      <circle cx="100" cy="84" r="40" fill={`url(#${ids.body})`} />
      <circle cx="100" cy="84" r="20" fill={`url(#${ids.inset})`} />
      <circle cx="100" cy="84" r="15" fill="var(--lf-bg-app)" />
      <path
        d="M74 60a40 40 0 0120-13"
        fill="none"
        stroke="var(--lf-bg-surface)"
        strokeWidth="4.5"
        strokeLinecap="round"
        opacity="0.5"
      />
      <Rim ids={ids} d="M62 102a44 44 0 0028 26" />
    </ClayScene>
  );
}

/** A path that stops short: 404. */
export function LostScene(props: SceneProps) {
  const ids = useSceneIds();
  return (
    <ClayScene {...props} tone={props.tone ?? "neutral"} ids={ids}>
      <Occlusion ids={ids}>
        <circle cx="138" cy="58" r="17" fill="var(--lf-text-primary)" />
      </Occlusion>

      {/* Stepping stones running out before they arrive. */}
      {[
        [56, 118, 15],
        [80, 108, 13],
        [102, 94, 11],
        [120, 78, 9],
      ].map(([cx, cy, r], i) => (
        <ellipse
          key={i}
          cx={cx}
          cy={cy}
          rx={r}
          ry={r * 0.62}
          fill={`url(#${ids.bodySoft})`}
          opacity={0.85 - i * 0.16}
        />
      ))}

      {/* The marker pin: a raised mass, not an outline. */}
      <path
        d="M138 30c13 0 24 11 24 24 0 17-24 38-24 38s-24-21-24-38c0-13 11-24 24-24z"
        fill={`url(#${ids.body})`}
      />
      <circle cx="138" cy="54" r="10" fill={`url(#${ids.inset})`} />
      <circle cx="138" cy="54" r="7" fill="var(--lf-bg-app)" />
      <path
        d="M122 44a24 24 0 0112-12"
        fill="none"
        stroke="var(--lf-bg-surface)"
        strokeWidth="4"
        strokeLinecap="round"
        opacity="0.5"
      />
      <Rim ids={ids} d="M117 66c3 12 21 26 21 26" />
    </ClayScene>
  );
}

/** A toppled stack: an unexpected server error. */
export function BrokenScene(props: SceneProps) {
  const ids = useSceneIds();
  return (
    <ClayScene {...props} tone={props.tone ?? "caution"} ids={ids}>
      <Occlusion ids={ids}>
        <rect x="52" y="40" width="96" height="40" rx="17" fill="var(--lf-text-primary)" />
        <rect x="56" y="92" width="44" height="38" rx="15" transform="rotate(-10 56 92)" fill="var(--lf-text-primary)" />
        <rect x="110" y="94" width="44" height="38" rx="15" transform="rotate(8 110 94)" fill="var(--lf-text-primary)" />
      </Occlusion>

      <rect x="52" y="40" width="96" height="40" rx="17" fill={`url(#${ids.body})`} />
      <rect x="62" y="48" width="76" height="12" rx="6" fill={`url(#${ids.face})`} opacity="0.6" />

      <rect
        x="56"
        y="92"
        width="44"
        height="38"
        rx="15"
        transform="rotate(-10 56 92)"
        fill={`url(#${ids.bodySoft})`}
      />
      <rect
        x="110"
        y="94"
        width="44"
        height="38"
        rx="15"
        transform="rotate(8 110 94)"
        fill={`url(#${ids.bodySoft})`}
      />
      <Rim ids={ids} d="M148 62v1a17 17 0 01-17 17H70" />
    </ClayScene>
  );
}

/** A considered signal: the AI insight surfaces. */
export function InsightScene(props: SceneProps) {
  const ids = useSceneIds();
  return (
    <ClayScene {...props} ids={ids}>
      <Occlusion ids={ids}>
        <circle cx="100" cy="74" r="34" fill="var(--lf-text-primary)" />
      </Occlusion>

      {/* Rays: raised bars, so they belong to the same material as the bulb. */}
      {[-52, -26, 0, 26, 52].map((angle) => (
        <rect
          key={angle}
          x="97"
          y="18"
          width="6"
          height="14"
          rx="3"
          fill={`url(#${ids.bodySoft})`}
          transform={`rotate(${angle} 100 74)`}
        />
      ))}

      <circle cx="100" cy="74" r="34" fill={`url(#${ids.body})`} />
      <circle cx="100" cy="74" r="22" fill={`url(#${ids.face})`} opacity="0.55" />
      <path
        d="M82 60a22 22 0 0113-11"
        fill="none"
        stroke="var(--lf-bg-surface)"
        strokeWidth="4"
        strokeLinecap="round"
        opacity="0.6"
      />

      {/* The base, stepped so it reads as stacked rather than printed. */}
      <rect x="86" y="108" width="28" height="11" rx="5.5" fill={`url(#${ids.body})`} />
      <rect x="90" y="121" width="20" height="9" rx="4.5" fill={`url(#${ids.bodySoft})`} />
      <Rim ids={ids} d="M68 88a34 34 0 0022 19" />
    </ClayScene>
  );
}
