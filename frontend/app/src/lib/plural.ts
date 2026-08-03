/**
 * Count plus correctly-inflected noun: `1 debt`, `3 debts`.
 *
 * Counts are interpolated into copy all over the product, and a hardcoded
 * trailing "s" reads as a bug the moment the count is exactly one — which is
 * precisely when a user is most likely to be looking, because one debt or one
 * account is where most people start.
 *
 * Irregular plurals take an explicit second form: `plural(n, "entry", "entries")`.
 */
export function plural(count: number, singular: string, pluralForm?: string): string {
  const noun = Math.abs(count) === 1 ? singular : (pluralForm ?? `${singular}s`);
  return `${count} ${noun}`;
}
