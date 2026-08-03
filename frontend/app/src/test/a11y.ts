import axe from "axe-core";

export interface A11yViolation {
  id: string;
  impact: string | null | undefined;
  help: string;
  nodes: string[];
}

/**
 * Run axe-core against a rendered container and return violations.
 *
 * Deliberately a plain helper rather than a custom matcher: the failure
 * output matters more than the ergonomics here, and returning structured
 * violations lets a test assert on *which* rules fired rather than just
 * "something is wrong somewhere."
 *
 * `color-contrast` is disabled in this environment, not because contrast
 * doesn't matter but because jsdom has no layout or paint engine — axe
 * cannot compute a real contrast ratio without rendered pixels, so leaving
 * it on produces neither passes nor failures, just "incomplete" noise.
 * Contrast is verified separately against real rendered screenshots.
 */
export async function findViolations(
  container: HTMLElement,
  options: { disableRules?: string[] } = {},
): Promise<A11yViolation[]> {
  const results = await axe.run(container, {
    rules: {
      "color-contrast": { enabled: false },
      ...Object.fromEntries((options.disableRules ?? []).map((id) => [id, { enabled: false }])),
    },
  });

  return results.violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    help: violation.help,
    nodes: violation.nodes.map((node) => node.html),
  }));
}

/** Format violations into a readable assertion message. */
export function describeViolations(violations: A11yViolation[]): string {
  if (violations.length === 0) return "no violations";
  return violations
    .map((v) => `[${v.impact ?? "unknown"}] ${v.id}: ${v.help}\n    ${v.nodes.join("\n    ")}`)
    .join("\n  ");
}
