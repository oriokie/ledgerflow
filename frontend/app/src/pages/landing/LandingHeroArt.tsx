import { DoodleScene, Figure, Wash, useDoodleIds } from "../../ui/illustration/DoodleScene";

/**
 * Landing-only hero: a modern, open composition showing people moving through
 * a clear financial plan. Floating sheets replace the literal desk scene.
 */
export function LandingHeroArt() {
  const ids = useDoodleIds();
  return (
    <DoodleScene title="Two people moving through a clear financial plan" ids={ids} chips>
      <Wash tone="accent" dx={4} dy={5} rotate={-2} opacity={0.22}>
        <rect x="91" y="34" width="72" height="48" rx="11" />
      </Wash>
      <rect x="91" y="34" width="72" height="48" rx="11" transform="rotate(2 127 58)" />
      <path d="M102 69V58M116 69V49M130 69V55M144 69V43" strokeWidth="5" opacity="0.5" />

      <Wash tone="positive" dx={3} dy={4} rotate={2} opacity={0.18}>
        <rect x="124" y="94" width="52" height="32" rx="9" />
      </Wash>
      <rect x="124" y="94" width="52" height="32" rx="9" transform="rotate(-2 150 110)" />
      <path d="M134 105h31M134 115h20" strokeWidth="2.2" opacity="0.45" />

      <path
        d="M39 91c24-28 47-26 69-5 16 15 30 13 48-4"
        strokeWidth="2.5"
        strokeDasharray="5 7"
        opacity="0.42"
      />
      <path d="M151 75l6 7-9 3" strokeWidth="2.5" opacity="0.52" />

      <Figure x={54} y={108} scale={1.18} arms="hold" hair="curly" tilt={-4} />
      <Figure x={102} y={116} scale={0.98} arms="point" hair="bun" tilt={3} flip />
    </DoodleScene>
  );
}
