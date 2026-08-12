import { DoodleScene, Figure, Wash, useDoodleIds } from "../../ui/illustration/DoodleScene";

export type AuthScene = "signin" | "signed-out";

/**
 * People-first artwork for the auth surface. These are small editorial scenes,
 * not enlarged security icons: the person and their relationship to the
 * product remain the subject.
 */
export function AuthHeroArt({ scene = "signin" }: { scene?: AuthScene }) {
  const ids = useDoodleIds();

  if (scene === "signed-out") {
    return (
      <DoodleScene ids={ids} chips={false}>
        <Wash tone="accent" dx={-6} dy={8} rotate={-4} opacity={0.28}>
          <path d="M96 36c28-18 62-8 70 22 8 28-10 54-38 62-26 8-54-6-62-32-6-22 6-42 30-52z" />
        </Wash>
        <path
          d="M42 118c18-28 40-46 72-52 28-6 52 4 64 28"
          strokeWidth="2.4"
          opacity="0.45"
        />
        <path d="M168 88l14-6M174 102l16 2M160 114l12 10" strokeWidth="2.2" opacity="0.5" />
        <Figure x={58} y={108} scale={1.48} arms="wave" hair="curly" tilt={-4} />
        <Figure x={98} y={118} scale={1.08} arms="down" hair="bun" tilt={6} flip />
        <path d="M28 142c30 6 64 6 96 0" strokeWidth="2.4" opacity="0.35" />
      </DoodleScene>
    );
  }

  return (
    <DoodleScene ids={ids} chips={false}>
      <Wash tone="accent" dx={4} dy={5} rotate={-2} opacity={0.24}>
          <rect x="112" y="39" width="62" height="50" rx="12" />
      </Wash>
        <rect x="112" y="39" width="62" height="50" rx="12" transform="rotate(1 143 64)" />
        <path d="M123 78V68M135 78V56M147 78V63M159 78V49" strokeWidth="5" opacity="0.55" />
        <path d="M121 85h42" strokeWidth="2.4" opacity="0.35" />
        <Figure x={48} y={104} scale={1.42} arms="point" hair="curly" tilt={-3} />
        <Figure x={91} y={112} scale={1.04} arms="hold" hair="long" seated tilt={3} flip />
        <path d="M25 141c27 5 57 5 87 0" strokeWidth="2.4" opacity="0.35" />
    </DoodleScene>
  );
}
