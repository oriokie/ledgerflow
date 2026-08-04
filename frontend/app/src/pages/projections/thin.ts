/**
 * Downsample a projection series for drawing.
 *
 * A forty-year projection is 480 points — more than a chart can draw legibly
 * and far more than it needs to, since at that length each pixel is roughly a
 * month. Thinning to a target count keeps the shape and drops the noise.
 *
 * The last point is always kept. Dropping it would end the line short of the
 * horizon the user asked for, which reads as the projection stopping early
 * rather than as a rendering choice.
 *
 * Lives outside the chart module so that file exports only components, which
 * is what keeps fast refresh working — the same reason `chartTheme.ts` is
 * component-free.
 */
export function thin<T>(points: T[], target = 120): T[] {
  if (points.length <= target) return points;
  const step = Math.ceil(points.length / target);
  const kept = points.filter((_, i) => i % step === 0);
  const last = points[points.length - 1];
  if (kept[kept.length - 1] !== last) kept.push(last);
  return kept;
}
