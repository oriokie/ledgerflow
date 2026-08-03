import type { Recommendation } from "../../api/types";
import { Heading } from "../../ui";

const SEVERITY_CLASS: Record<string, string> = {
  info: "lf-insight--good",
  warning: "lf-insight--soon",
  critical: "lf-insight--attention",
};

export function InsightsSection({ recommendations }: { recommendations: Recommendation[] | undefined }) {
  const items = (recommendations ?? []).slice(0, 4);
  if (items.length === 0) return null;

  return (
    <section className="lf-dash-section">
      <div className="lf-section-head">
        <Heading level={2}>Insights</Heading>
      </div>
      <div className="lf-grid lf-grid--2 lf-gap-4">
        {items.map((rec, i) => (
          <div key={i} className={`lf-insight ${SEVERITY_CLASS[rec.severity] ?? "lf-insight--good"}`}>
            <p className="lf-insight-title">{rec.title}</p>
            <p className="lf-insight-body">{rec.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
