import type { ReactNode } from "react";
import { Heading, Text } from "../../ui";

/**
 * The header every admin page opens with.
 *
 * Before this existed each page hand-rolled its own: four arrangements across
 * eleven screens, and nine of them a bare title with nothing under it. A
 * console page whose header says only "Promotions" makes the operator work out
 * what the screen is for and how much of it there is — the two things a header
 * exists to say.
 *
 * `description` is one sentence of operator-useful fact, not marketing. The
 * discipline worth keeping: describe what the page *does to other people's
 * accounts* ("ending a promotion stops new redemptions; existing discounts
 * run their course"), because that is the sentence an operator actually needs
 * before acting.
 *
 * `meta` is for the row count the API already returns on every paginated
 * response and no page was showing. With 25 rows on screen and 140 in the
 * database, a table without the total quietly misrepresents the estate.
 */
export function AdminPageHeader({
  title,
  description,
  meta,
  actions,
}: {
  title: string;
  description?: ReactNode;
  /** Small factual annotation beside the title — usually the total count. */
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="lf-admin-page-head">
      <div className="lf-admin-page-head-text">
        <p className="lf-admin-page-eyebrow">Platform</p>
        <div className="lf-admin-page-title-row">
          <Heading level={1}>{title}</Heading>
          {meta != null && <span className="lf-admin-page-meta">{meta}</span>}
        </div>
        {description && (
          <Text tone="secondary" size="sm" className="lf-admin-page-desc">
            {description}
          </Text>
        )}
      </div>
      {actions && <div className="lf-admin-page-actions">{actions}</div>}
    </header>
  );
}
