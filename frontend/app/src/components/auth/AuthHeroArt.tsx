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
        <Wash tone="accent" dx={5} dy={5} rotate={2} opacity={0.22}>
          <path d="M108 43h58v54h-58z" />
        </Wash>
        <path d="M108 43h58v54h-58zM118 57h38M118 70h28M118 83h34" opacity="0.7" />
        <path d="M105 109h30M127 101l8 8-8 8" strokeWidth="2.8" />
        <Figure x={54} y={104} scale={1.42} arms="wave" hair="bun" tilt={-3} />
        <Figure x={93} y={112} scale={1.05} arms="down" hair="short" tilt={4} flip />
        <path d="M27 141c26 5 54 5 82 0" strokeWidth="2.4" opacity="0.35" />
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
