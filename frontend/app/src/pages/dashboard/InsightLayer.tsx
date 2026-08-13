import { Link } from "react-router-dom";
import type { Insight, Recommendation } from "../../api/types";
import { InsightCardCompact } from "../coach";

export function InsightLayer({
  insights,
  recommendations,
  aiEnabled,
}: {
  insights: Insight[] | undefined;
  recommendations: Recommendation[] | undefined;
  aiEnabled: boolean;
}) {
  const top = (insights ?? []).slice(0, 3);
  const recs = aiEnabled ? (recommendations ?? []).slice(0, 2) : [];

  if (top.length === 0 && recs.length === 0) return null;

  return (
    <section className="lf-cmd-panel" aria-labelledby="lf-insight-title">
      <header className="lf-cmd-panel-head">
        <h2 id="lf-insight-title">Insights</h2>
        <Link className="lf-section-link" to="/insights?tab=coach">
          All insights
        </Link>
      </header>

      {top.length > 0 && (
        <div className="lf-coach-feed">
          {top.map((insight) => (
            <InsightCardCompact key={insight.id} insight={insight} />
          ))}
        </div>
      )}

      {recs.length > 0 && (
        <div className="lf-insight-recs">
          {recs.map((rec) => (
            <article
              key={`${rec.kind}-${rec.title}`}
              className={`lf-insight ${
                rec.severity === "critical"
                  ? "lf-insight--attention"
                  : rec.severity === "warning"
                    ? "lf-insight--soon"
                    : "lf-insight--good"
              }`}
            >
              <p className="lf-insight-title">{rec.title}</p>
              <p className="lf-insight-body">{rec.body}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
