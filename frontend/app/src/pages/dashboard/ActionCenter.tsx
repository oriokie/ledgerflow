import { Link } from "react-router-dom";
import { Illustration } from "../../ui/illustration";
import type { AttentionItem } from "./personalization";

export function ActionCenter({ items }: { items: AttentionItem[] }) {
  if (items.length === 0) {
    return (
      <section className="lf-cmd-panel lf-cmd-panel--rail" aria-labelledby="lf-attn-title">
        <header className="lf-cmd-panel-head">
          <h2 id="lf-attn-title">Needs your attention</h2>
        </header>
        <div className="lf-cmd-quiet lf-cmd-quiet--compact">
          <Illustration name="success" size="spot" />
          <p>Nothing urgent. Bills, missed income, and cash-flow risks will surface here when they do.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="lf-cmd-panel lf-cmd-panel--rail lf-cmd-enter" aria-labelledby="lf-attn-title">
      <header className="lf-cmd-panel-head">
        <h2 id="lf-attn-title">Needs your attention</h2>
        <span className="lf-cmd-count">{items.length}</span>
      </header>
      <ul className="lf-attn-list">
        {items.map((item) => (
          <li key={item.id} className="lf-attn-item" data-kind={item.kind}>
            <div className="lf-attn-copy">
              <p className="lf-attn-title">{item.title}</p>
              <p className="lf-attn-body">{item.body}</p>
            </div>
            <Link className="lf-btn lf-btn--secondary lf-btn--sm" to={item.href}>
              {item.cta}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
