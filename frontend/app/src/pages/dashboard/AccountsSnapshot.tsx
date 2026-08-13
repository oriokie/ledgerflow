import { Link } from "react-router-dom";
import type { FinancialAccount } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Illustration } from "../../ui/illustration";

export function AccountsSnapshot({
  accounts,
  currency,
}: {
  accounts: FinancialAccount[] | undefined;
  currency: string;
}) {
  const visible = (accounts ?? [])
    .filter((a) => !a.is_archived && !a.is_hidden)
    .slice()
    .sort((a, b) => Math.abs(b.balance_minor) - Math.abs(a.balance_minor))
    .slice(0, 5);

  return (
    <section className="lf-cmd-panel lf-cmd-panel--rail" aria-labelledby="lf-acct-title">
      <header className="lf-cmd-panel-head">
        <h2 id="lf-acct-title">Accounts</h2>
        <Link className="lf-section-link" to="/accounts">
          All accounts
        </Link>
      </header>

      {visible.length === 0 ? (
        <div className="lf-cmd-quiet lf-cmd-quiet--compact">
          <Illustration name="vault" size="spot" />
          <p>No accounts yet.</p>
          <Link className="lf-btn lf-btn--secondary lf-btn--sm" to="/accounts">
            Add account
          </Link>
        </div>
      ) : (
        <ul className="lf-acct-list">
          {visible.map((a) => (
            <li key={a.id} className="lf-acct-row">
              <div className="lf-acct-main">
                <span className="lf-acct-name">{a.name}</span>
                <span className="lf-acct-type">{a.account_type.replace(/_/g, " ")}</span>
              </div>
              <span className="lf-acct-bal">
                {formatAmount(a.balance_minor, a.currency || currency)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
