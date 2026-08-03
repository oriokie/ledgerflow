import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Illustration, type IllustrationName } from "./illustration";

interface EmptyStateProps {
  icon: LucideIcon;
  /**
   * Use the illustration system instead of the icon plate.
   *
   * Opt-in, and deliberately so. An empty state inside a data screen — an
   * unfiltered table, a chart with no rows — keeps the quiet icon plate,
   * because artwork there competes with the numbers around it. The
   * illustration is for the states that own their whole surface: a workspace
   * with nothing in it yet, a search that found nothing, a completed action.
   */
  illustration?: IllustrationName;
  title: string;
  body: string;
  /**
   * Heading level for the title. Defaults to 2 — an empty state stands in for
   * a section, and a page's <h1> is right above it. Pass 3 when the empty
   * state sits inside a card that already has its own <h2>.
   */
  level?: 2 | 3 | 4;
  /** The recommended next action. */
  action?: ReactNode;
  /** A lower-commitment alternative (import, learn more, see an example). */
  secondaryAction?: ReactNode;
  /**
   * Two or three short pointers about what this surface will do once it has
   * data. An empty state is the best onboarding real estate in the product —
   * it has the user's full attention and nothing to compete with.
   */
  tips?: string[];
}

/**
 * The `.lf-empty` treatment: an invitation to act, not a shrug.
 *
 * The illustration is a token-built plate — concentric rings fading outward
 * behind the section's own icon — rather than stock art. It costs nothing to
 * ship, recolors with the theme and accent automatically, and stays coherent
 * across every empty surface in the product.
 */
export function EmptyState({
  icon: Icon,
  illustration,
  title,
  body,
  action,
  secondaryAction,
  tips,
  level = 2,
}: EmptyStateProps) {
  // An empty state replaces a section's content, so its title is that
  // section's heading. Hardcoding <h3> under a page's <h1> skipped a level on
  // every route that uses this — eight of them — which is a 1.3.1 failure and
  // leaves a screen-reader user with a broken outline of the page.
  const Title = `h${level}` as "h2" | "h3" | "h4";
  return (
    <div className="lf-empty">
      {illustration ? (
        <Illustration name={illustration} size="spot" />
      ) : (
        <div className="lf-empty-art" aria-hidden="true">
          <span className="lf-empty-ring lf-empty-ring--outer" />
          <span className="lf-empty-ring lf-empty-ring--inner" />
          <span className="lf-empty-icon">
            <Icon size={26} strokeWidth={1.5} aria-hidden="true" />
          </span>
        </div>
      )}

      <Title className="lf-empty-title">{title}</Title>
      <p>{body}</p>

      {(action || secondaryAction) && (
        <div className="lf-empty-actions">
          {action}
          {secondaryAction}
        </div>
      )}

      {tips && tips.length > 0 && (
        <ul className="lf-empty-tips">
          {tips.map((tip) => (
            <li key={tip}>{tip}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
