import type { HealthScore } from "../../api/types";
import { greeting } from "./insightsCopy";

/** A warm, plain-language opener that sets the tone and points at what (if
 * anything) needs doing — with an honest note on the data it's drawn from. */
export function InsightsGreeting({ health, guidanceCount }: { health: HealthScore | undefined; guidanceCount: number }) {
  const { title, subtitle } = greeting(health, guidanceCount);
  return (
    <header className="lf-insights-greeting">
      <h1 className="lf-insights-greeting-title">{title}</h1>
      <p className="lf-insights-greeting-sub">{subtitle}</p>
      <p className="lf-insights-basis">Drawn from your recent accounts, budgets, and spending — not financial advice.</p>
    </header>
  );
}
