import type { AllocationSlice } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Text } from "../../ui";

/** Steps in `--lf-ramp-*`. Slices past this share the last step — by then they
 * are slivers, and the list beneath is what identifies them anyway. */
const RAMP_STEPS = 6;

/**
 * Portfolio allocation, as one ordered bar.
 *
 * This was a donut with a six-colour categorical ramp and a recharts `Legend`,
 * which had three problems stacked on each other:
 *
 * 1. It read `var(--lf-chart-6)`, **a token that does not exist**. A portfolio
 *    with six or more slices handed recharts an invalid `fill`.
 * 2. Identifying a slice meant matching its colour to a legend entry. Phase 2
 *    established that a six-way categorical set cannot hold its separation
 *    under deuteranopia at these contrast constraints — so for some readers
 *    that match is not available.
 * 3. Reading a proportion off a donut is a famously poor perceptual task:
 *    angle and arc area are judged far less accurately than length.
 *
 * A single stacked bar fixes all three at once. Length is the encoding, order
 * is largest-first, the list beneath repeats that order with an exact
 * percentage against every label, and `--lf-ramp-*` is a sequential ramp whose
 * job is only to show where one segment ends and the next begins.
 *
 * The bar is `aria-hidden`; the list is the accessible representation, and it
 * is genuinely the easier of the two to read exact figures from.
 */
export function AllocationChart({
  title,
  slices,
  currency,
  level = 2,
}: {
  title: string;
  slices: AllocationSlice[];
  currency: string;
  /**
   * Heading level for the title. Defaults to 2 — an allocation breakdown is a
   * section of the page, and the page's <h1> is above it. This was hardcoded
   * to <h3>, which skipped a level under that <h1> (WCAG 1.3.1) while the
   * sibling "Holdings" section next to it was correctly an <h2>. The route
   * audit only caught it once the page had data to render.
   */
  level?: 2 | 3 | 4;
}) {
  const Title = `h${level}` as "h2" | "h3" | "h4";
  if (slices.length === 0) {
    return (
      <div className="lf-allocation">
        <Title className="lf-allocation-title">{title}</Title>
        <Text tone="tertiary" size="sm">
          Add prices to your holdings to see this breakdown.
        </Text>
      </div>
    );
  }

  const rank = (i: number) => Math.min(i + 1, RAMP_STEPS);

  return (
    <div className="lf-allocation">
      <Title className="lf-allocation-title">{title}</Title>

      <div className="lf-alloc-bar" aria-hidden="true">
        {slices.map((slice, i) => (
          <span
            key={slice.label}
            className="lf-alloc-seg"
            data-rank={rank(i)}
            style={{ width: `${slice.percent}%` }}
          />
        ))}
      </div>

      <ul className="lf-alloc-list">
        {slices.map((slice, i) => (
          <li key={slice.label}>
            <span className="lf-alloc-swatch" data-rank={rank(i)} aria-hidden="true" />
            <span className="lf-alloc-label">{slice.label}</span>
            <span className="lf-alloc-pct">{slice.percent}%</span>
            <span className="lf-alloc-value">
              {formatAmount(slice.market_value_minor, currency)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
