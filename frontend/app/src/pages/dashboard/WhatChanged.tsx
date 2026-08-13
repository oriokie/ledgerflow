import { Link } from "react-router-dom";
import { Illustration } from "../../ui/illustration";
import type { ChangeInsight } from "./personalization";

export function WhatChanged({ insights }: { insights: ChangeInsight[] }) {
  if (insights.length === 0) {
    return (
      <section className="lf-cmd-panel" aria-labelledby="lf-changed-title">
        <header className="lf-cmd-panel-head">
          <h2 id="lf-changed-title">Since you last looked</h2>
        </header>
        <div className="lf-cmd-quiet">
          <Illustration name="waiting" size="spot" />
          <p>Not enough movement yet to summarize. Keep logging activity and trends will appear here.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="lf-cmd-panel lf-cmd-enter" aria-labelledby="lf-changed-title">
      <header className="lf-cmd-panel-head">
        <h2 id="lf-changed-title">Since you last looked</h2>
        <Link className="lf-section-link" to="/insights?tab=trends">
          Trends
        </Link>
      </header>
      <ul className="lf-changed-list">
        {insights.map((item) => (
          <li key={item.id} className="lf-changed-item" data-tone={item.tone}>
            <span className="lf-changed-mark" aria-hidden="true" />
            <div>
              <p className="lf-changed-title">{item.title}</p>
              <p className="lf-changed-body">{item.body}</p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
