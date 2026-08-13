import type { HealthScore } from "../../api/types";
import { greeting } from "./insightsCopy";

/** A warm, plain-language opener that sets the tone and points at what (if
 * anything) needs doing — with an honest note on the data it's drawn from.
 *
 * `embedded` renders this as a tab panel inside the Insights hub, which owns
 * the page's <h1>. Demoted to an <h2> rather than dropped: the greeting
 * itself is still worth having, it just can't be a second top-level heading. */
export function InsightsGreeting({
  health,
  guidanceCount,
  embedded,
}: {
  health: HealthScore | undefined;
  guidanceCount: number;
  embedded?: boolean;
}) {
  const { title, subtitle } = greeting(health, guidanceCount);
  const TitleTag = (embedded ? "h2" : "h1") as "h1" | "h2";
  return (
    <header className="lf-insights-greeting">
      <TitleTag className="lf-insights-greeting-title">{title}</TitleTag>
      <p className="lf-insights-greeting-sub">{subtitle}</p>
      <p className="lf-insights-basis">Drawn from your recent accounts, budgets, and spending — not financial advice.</p>
    </header>
  );
}
