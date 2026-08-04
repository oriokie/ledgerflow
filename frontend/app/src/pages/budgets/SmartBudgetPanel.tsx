import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { budgetingApi } from "../../api/budgeting";
import { ApiError } from "../../api/client";
import type { SmartBudgetProposal } from "../../api/types";
import { formatAmount } from "../../lib/money";
import { Badge, Banner, Button, Card, Skeleton, Text } from "../../ui";

/**
 * A budget assembled from what the workspace already knows.
 *
 * The first budget is the hardest one: it asks for numbers most people have
 * never measured, at the moment they have the least data in front of them.
 * This panel shows the draft the engine assembled — history medians, committed
 * bills as floors, income minus debt minimums minus what the goals need — and
 * every line carries the reasoning that produced it, because a number a person
 * cannot interrogate is a number they will not trust.
 *
 * Nothing happens until Apply. The proposal is recomputed on each open and
 * stored nowhere; applying creates a normal budget the user edits like any
 * other. A draft they own, not a rule they obey.
 */
export function SmartBudgetPanel({
  onCreated,
  onCancel,
}: {
  onCreated: (budgetId: string) => void;
  onCancel: () => void;
}) {
  const [proposal, setProposal] = useState<SmartBudgetProposal | null>(null);
  const [loading, setLoading] = useState(true);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    budgetingApi
      .suggestBudget()
      .then((data) => {
        if (!cancelled) setProposal(data);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof ApiError ? err.detail : "Couldn't put a suggestion together.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const apply = async () => {
    setApplying(true);
    setError(null);
    try {
      const result = await budgetingApi.applySuggestedBudget();
      onCreated(result.budget.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't create the budget.");
      setApplying(false);
    }
  };

  if (loading) {
    return (
      <Card title="Suggested budget">
        <Skeleton width="60%" />
      </Card>
    );
  }

  if (error && !proposal) {
    return (
      <Card title="Suggested budget">
        <Banner tone="info">{error}</Banner>
        <div style={{ marginTop: "var(--lf-space-3)" }}>
          <Button variant="ghost" onClick={onCancel}>
            Close
          </Button>
        </div>
      </Card>
    );
  }

  if (!proposal) return null;

  const money = (minor: number) => formatAmount(minor, proposal.currency);
  const trimmedPct = Math.round((1 - proposal.trim_factor) * 100);

  return (
    <Card
      title="Suggested budget"
      action={
        <Badge tone="neutral">
          <Sparkles size={12} strokeWidth={2} aria-hidden="true" /> from your last{" "}
          {proposal.months_considered} months
        </Badge>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-4)" }}>
        {/* The envelope math, stated before the lines: the reader should see
            why the totals are what they are before judging any one number. */}
        <dl className="lf-smart-envelope">
          {proposal.income_known ? (
            <>
              <div>
                <dt>Monthly income</dt>
                <dd>{money(proposal.income_minor)}</dd>
              </div>
              {proposal.debt_minimums_minor > 0 && (
                <div>
                  <dt>Debt minimums</dt>
                  <dd>−{money(proposal.debt_minimums_minor)}</dd>
                </div>
              )}
              {proposal.savings_target_minor > 0 && (
                <div>
                  <dt>Savings goals</dt>
                  <dd>−{money(proposal.savings_target_minor)}</dd>
                </div>
              )}
              <div>
                <dt>Left to budget</dt>
                <dd>{money(proposal.envelope_minor)}</dd>
              </div>
            </>
          ) : (
            <Text tone="secondary" size="sm">
              No income recorded yet, so this draft mirrors your spending history without trimming.
              Add an income source and the suggestion will fit itself to what you earn.
            </Text>
          )}
        </dl>

        {proposal.deficit && (
          <Banner tone="danger">
            Your recurring commitments alone exceed your income — no budget can fix that arithmetic.
            The lines below hold each category at its committed amount so you can see where the
            pressure is.
          </Banner>
        )}
        {!proposal.deficit && trimmedPct > 0 && (
          <Banner tone="info">
            Your recent spending runs ahead of what's left after savings, so flexible categories are
            trimmed {trimmedPct}% from their history. Committed bills are never trimmed.
          </Banner>
        )}

        <table className="lf-smart-lines">
          <thead>
            <tr>
              <th scope="col">Category</th>
              <th scope="col" className="lf-num">
                Suggested
              </th>
              <th scope="col">Why</th>
            </tr>
          </thead>
          <tbody>
            {proposal.lines.map((line) => (
              <tr key={line.category_id}>
                <td>{line.category_name}</td>
                <td className="lf-num">{money(line.limit_minor)}</td>
                <td>
                  <Text tone="tertiary" size="xs" as="span">
                    {line.rationale}
                  </Text>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">Total</th>
              <td className="lf-num">{money(proposal.total_minor)}</td>
              <td>
                {proposal.income_known && proposal.left_over_minor > 0 && (
                  <Text tone="tertiary" size="xs" as="span">
                    leaves {money(proposal.left_over_minor)} unallocated — headroom is what keeps a
                    budget alive
                  </Text>
                )}
              </td>
            </tr>
          </tfoot>
        </table>

        {error && <Banner tone="danger">{error}</Banner>}

        <div style={{ display: "flex", gap: "var(--lf-space-2)" }}>
          <Button variant="primary" loading={applying} onClick={apply}>
            Use this budget
          </Button>
          <Button variant="ghost" disabled={applying} onClick={onCancel}>
            Not now
          </Button>
        </div>
        <Text tone="tertiary" size="xs">
          You can edit every line after applying — this is a first draft, not a rule.
        </Text>
      </div>
    </Card>
  );
}
