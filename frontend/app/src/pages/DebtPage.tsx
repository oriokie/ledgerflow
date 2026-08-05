import { CreditCard, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import type { DebtView, PayoffStrategy } from "../api/types";
import {
  useBorrowingCost,
  useDebtAnalytics,
  useDebts,
  useDebtStress,
  useDebtSummary,
  useDeleteDebt,
  usePayoffPlan,
  useTrackedLiabilities,
} from "../hooks/useDebt";
import { debtApi } from "../api/debt";
import { majorToMinor } from "../lib/money";
import { plural } from "../lib/plural";
import { Button, Card, EmptyState, Inline, Input, Money, PageHeader, SkeletonCard, Text } from "../ui";
import {
  BorrowingCostCard,
  ConsolidationModal,
  CreateDebtModal,
  DebtAnalytics,
  DebtStressCard,
  DebtSummaryCard,
  DebtTermsModal,
  PayoffCalendar,
  RefinanceModal,
  StrategyComparison,
} from "./debt";

/**
 * The debt planner.
 *
 * Ordered by what a user needs before they can decide anything: what's owed and
 * what it costs, then which approach, then the schedule, then the debts
 * themselves. The extra-payment field sits with the strategy comparison because
 * the two only mean anything together — a strategy with no spare money is just
 * an ordering.
 */
export function DebtPage() {
  const [strategy, setStrategy] = useState<PayoffStrategy>("avalanche");
  const [extraInput, setExtraInput] = useState("");
  const [editing, setEditing] = useState<DebtView | null>(null);
  const [refinancing, setRefinancing] = useState<DebtView | null>(null);
  const [consolidating, setConsolidating] = useState(false);
  const [creating, setCreating] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const deleteDebt = useDeleteDebt();

  const extraMinor = extraInput ? majorToMinor(Number(extraInput) || 0) : 0;

  const { data: summary, isLoading } = useDebtSummary(extraMinor);
  const { data: debts } = useDebts();
  // Accounts that exist but owe nothing. Without this the page cannot tell
  // "no cards" from "a card you just added and haven't used", and shows the
  // same empty state for both — so following its own advice appears to fail.
  const { data: tracked } = useTrackedLiabilities();
  const { data: stress } = useDebtStress();
  const { data: cost } = useBorrowingCost();
  const { data: analytics } = useDebtAnalytics({ strategy, extra_monthly_minor: extraMinor, months: 24 });
  const { data: plan } = usePayoffPlan({
    strategy,
    extra_monthly_minor: extraMinor,
    months: 12,
  });

  const currency = summary?.currency ?? "USD";

  // The cards that can't compute a figure offer the fix rather than just
  // reporting the gap. `debt_views` sorts largest balance first, so the first
  // match is the debt whose missing terms distort the picture most.
  const untermed = (debts ?? []).find((d) => !d.has_terms) ?? null;
  const addTerms = untermed ? () => setEditing(untermed) : undefined;

  return (
    <>
      <PageHeader
        title="Debt"
        eyebrow={summary ? plural(summary.debt_count, "debt") : undefined}
        description="What you owe, what it's costing, and the fastest way out."
        actions={
          // Only once there is something to add *to*. While the page is empty
          // the empty state carries the CTA, and two identical buttons on one
          // screen is the duplication the dashboard header already avoids.
          summary ? (
            <Button variant="primary" onClick={() => setCreating(true)}>
              Add a debt
            </Button>
          ) : undefined
        }
      />

      {isLoading && <SkeletonCard />}

      {!isLoading && !summary && (tracked?.length ?? 0) > 0 && (
        <Card title="Tracked accounts" ruledHeader>
          <Text tone="secondary" size="sm">
            Nothing is owed on these right now, so there is no payoff plan to
            make. They will appear in the planner as soon as they carry a
            balance.
          </Text>
          <ul className="lf-debt-tracked">
            {(tracked ?? []).map((row) => (
              <li key={row.account_id}>
                <div>
                  <strong>{row.name}</strong>
                  <Text size="xs" tone="tertiary">
                    {row.has_terms
                      ? `${row.apr}% APR · minimum ${row.minimum_payment_minor / 100} ${row.currency}`
                      : "No interest rate or minimum payment recorded yet"}
                  </Text>
                </div>
                <Money amountMinor={row.balance_minor} currency={row.currency} neutral />
              </li>
            ))}
          </ul>
          <Inline gap={2}>
            {/* Opens the debt form itself. This used to navigate to
                /accounts?add=1, which created a bare account with no terms and
                left the planner still empty — the button appeared to do nothing
                but change the subject. */}
            <Button variant="secondary" onClick={() => setCreating(true)}>
              Add a credit card or loan
            </Button>
          </Inline>
        </Card>
      )}

      {!isLoading && !summary && (tracked?.length ?? 0) === 0 && (
        <Card>
          <EmptyState
            icon={CreditCard}
            illustration="no-data"
            title="No debt tracked"
            body="Cards, loans, and money borrowed from someone you know. Adding one here sets up the account behind it too, so nothing gets entered twice."
            tips={[
              "Only a name and the amount owed are required — the rate and minimum payment can wait.",
              "Balances update from your transactions automatically once it exists.",
              "The planner compares paying off the most expensive debt first against the smallest.",
            ]}
            action={
              <Button variant="primary" onClick={() => setCreating(true)}>
                Add a debt
              </Button>
            }
          />
        </Card>
      )}

      {summary && (
        <>
          <div className="lf-dash-section">
            <Card prominence="primary">
              <DebtSummaryCard summary={summary} onAddTerms={addTerms} />
            </Card>
          </div>

          {(stress || cost) && (
            <div className="lf-dash-section lf-dash-split">
              {stress && (
                <Card>
                  <DebtStressCard stress={stress} />
                </Card>
              )}
              {cost && (
                <Card>
                  <BorrowingCostCard cost={cost} onAddTerms={addTerms} />
                </Card>
              )}
            </div>
          )}

          <div className="lf-dash-section">
            <Card title="How to tackle it">
              <div className="lf-debt-extra">
                <Input
                  label="Extra you could put toward debt each month"
                  amount
                  inputMode="decimal"
                  placeholder="0.00"
                  hint="On top of the minimums. Try a figure and watch the plan change."
                  value={extraInput}
                  onChange={(e) => setExtraInput(e.target.value)}
                />
                {plan && plan.months_to_debt_free !== null && (
                  <p className="lf-debt-extra-result">
                    Debt free in <strong>{plan.months_to_debt_free} months</strong>
                    {plan.debt_free_on && (
                      <>
                        {" "}
                        —{" "}
                        {new Date(plan.debt_free_on).toLocaleDateString(undefined, {
                          month: "long",
                          year: "numeric",
                        })}
                      </>
                    )}
                  </p>
                )}
              </div>

              <StrategyComparison
                comparisons={plan?.comparison ?? []}
                selected={strategy}
                currency={currency}
                onSelect={setStrategy}
              />

              <div className="lf-debt-simulators">
                <Text as="span" tone="tertiary" size="xs">
                  Been offered better terms?
                </Text>
                <Inline gap={2}>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setConsolidating(true)}
                    disabled={(debts ?? []).filter((d) => d.has_terms).length < 2}
                  >
                    Compare a consolidation loan
                  </Button>
                </Inline>
              </div>

              {/* A plan that can't finish is the most important thing on the
                  page when it happens. */}
              {plan && !plan.is_complete && plan.stuck_debt_ids.length > 0 && (
                <p className="lf-debt-stuck" role="status">
                  At these payments the balance never clears — the interest is more than the
                  payments cover. Putting more toward it each month is the only way out.
                </p>
              )}
            </Card>
          </div>

          {analytics && (
            <div className="lf-dash-section">
              <Card title="Analytics">
                <DebtAnalytics
                  analytics={analytics}
                  exportPath={debtApi.exportPath(strategy, extraMinor)}
                />
              </Card>
            </div>
          )}

          {plan && plan.calendar.length > 0 && (
            <div className="lf-dash-section">
              <Card title="Payment schedule">
                <PayoffCalendar months={plan.calendar} currency={currency} />
              </Card>
            </div>
          )}

          <div className="lf-dash-section">
            <h2 className="lf-section-title">Your debts</h2>
            <div className="lf-table-wrap">
              <table className="lf-table">
                <caption className="lf-visually-hidden">Debts</caption>
                <thead>
                  <tr>
                    <th scope="col">Debt</th>
                    <th scope="col" className="lf-col-amount">Balance</th>
                    <th scope="col" className="lf-col-amount lf-col-hide-mobile">Rate</th>
                    <th scope="col" className="lf-col-amount lf-col-hide-mobile">Minimum</th>
                    <th scope="col" className="lf-col-actions" />
                  </tr>
                </thead>
                <tbody>
                  {(debts ?? []).map((debt) => (
                    <tr key={debt.account_id}>
                      <td>
                        <span className="lf-cell-primary">{debt.name}</span>
                        <br />
                        <span className="lf-cell-meta">
                          {debt.has_terms ? (
                            <>
                              {debt.monthly_interest_minor > 0 && (
                                <>
                                  <Money
                                    amountMinor={debt.monthly_interest_minor}
                                    currency={debt.currency}
                                    neutral
                                  />
                                  {" a month in interest"}
                                </>
                              )}
                              {debt.percent_repaid !== null && ` · ${debt.percent_repaid}% repaid`}
                              {typeof debt.promo_days_remaining === "number" && (
                                <span className="lf-debt-promo">
                                  {" · "}
                                  {debt.promo_days_remaining <= 60
                                    ? `promo rate ends in ${debt.promo_days_remaining} days`
                                    : "promotional rate"}
                                </span>
                              )}
                              {debt.next_rate_change_on && (
                                <span className="lf-debt-rate-change">
                                  {` · rate moves to ${debt.next_rate_apr}% on ${new Date(
                                    debt.next_rate_change_on,
                                  ).toLocaleDateString(undefined, { month: "short", year: "numeric" })}`}
                                </span>
                              )}
                            </>
                          ) : (
                            "No terms recorded"
                          )}
                        </span>
                      </td>
                      <td className="lf-col-amount">
                        <Money amountMinor={debt.balance_minor} currency={debt.currency} neutral />
                      </td>
                      <td className="lf-col-amount lf-col-hide-mobile">
                        {debt.has_terms ? `${debt.apr}%` : <Text as="span" tone="tertiary" size="sm">—</Text>}
                      </td>
                      <td className="lf-col-amount lf-col-hide-mobile">
                        {debt.minimum_payment_minor > 0 ? (
                          <Money
                            amountMinor={debt.minimum_payment_minor}
                            currency={debt.currency}
                            neutral
                          />
                        ) : (
                          <Text as="span" tone="tertiary" size="sm">—</Text>
                        )}
                      </td>
                      <td className="lf-col-actions">
                        <Inline gap={1}>
                          {debt.has_terms && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setRefinancing(debt)}
                            >
                              Refinance?
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setEditing(debt)}
                            icon={<Pencil size={14} aria-hidden="true" />}
                          >
                            {debt.has_terms ? "Edit" : "Add terms"}
                          </Button>
                          {/* Two-step, because deleting a debt takes its
                              account with it. Where the account has posted
                              transactions the server archives instead, so the
                              history survives either way. */}
                          {confirmDelete === debt.account_id ? (
                            <>
                              <Button
                                variant="danger"
                                size="sm"
                                loading={deleteDebt.isPending}
                                onClick={async () => {
                                  await deleteDebt.mutateAsync(debt.account_id);
                                  setConfirmDelete(null);
                                }}
                              >
                                Delete
                              </Button>
                              <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(null)}>
                                Keep
                              </Button>
                            </>
                          ) : (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setConfirmDelete(debt.account_id)}
                              icon={<Trash2 size={14} aria-hidden="true" />}
                            >
                              Delete
                            </Button>
                          )}
                        </Inline>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      <CreateDebtModal open={creating} onClose={() => setCreating(false)} />
      <DebtTermsModal debt={editing} onClose={() => setEditing(null)} />
      <RefinanceModal debt={refinancing} onClose={() => setRefinancing(null)} />
      <ConsolidationModal
        open={consolidating}
        debts={debts ?? []}
        onClose={() => setConsolidating(false)}
      />
    </>
  );
}
