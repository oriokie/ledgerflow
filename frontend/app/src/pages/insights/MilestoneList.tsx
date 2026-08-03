import { Flag } from "lucide-react";
import type { Milestone } from "../../api/types";
import { formatDateLong } from "../../lib/money";
import { Text } from "../../ui";

/**
 * Things that have already happened.
 *
 * Deliberately not a trophy cabinet. Each row is a dated fact reconstructed
 * from the ledger — "you passed 50,000 for the first time, in March" — with the
 * date carrying as much weight as the figure, because the date is what makes it
 * a record rather than a reward. There is no progress bar to a next tier, no
 * count of how many you have, and nothing here can be lost.
 *
 * Renders nothing at all when there are none. An empty "Milestones" heading is
 * a standing reminder that you have not achieved anything, which is the exact
 * opposite of the point.
 */
export function MilestoneList({ milestones }: { milestones: Milestone[] }) {
  if (milestones.length === 0) return null;

  return (
    <section className="lf-milestones" aria-label="Milestones">
      <ul>
        {milestones.map((m) => (
          <li key={m.key}>
            <span className="lf-milestone-icon" aria-hidden="true">
              <Flag size={14} strokeWidth={2} />
            </span>
            <div>
              <p className="lf-milestone-title">{m.title}</p>
              <Text as="span" tone="tertiary" size="xs">
                {formatDateLong(m.achieved_on)} · {m.detail}
              </Text>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
