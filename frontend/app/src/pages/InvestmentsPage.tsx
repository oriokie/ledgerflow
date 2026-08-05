import { Plus, TagIcon, TrendingUp } from "lucide-react";
import { useState } from "react";
import { useAccounts } from "../hooks/useFinance";
import { useHoldings, usePortfolio, usePortfolioHistory, useSecurities } from "../hooks/useInvestments";
import { useAuth } from "../lib/AuthContext";
import { Button, Card, EmptyState, Grid, Inline, PageHeader, SkeletonCard } from "../ui";
import {
  AllocationChart,
  HoldingsTable,
  PerformanceChart,
  PortfolioSummaryCard,
  IncomeModal,
  PriceModal,
  SecuritiesTable,
  SecurityModal,
  TradeModal,
} from "./investments";

/**
 * The portfolio dashboard.
 *
 * Ordered by what a user checks first: what it's worth, then how it got there,
 * then what's in it. Allocation sits above the holdings table because "am I
 * diversified?" is a question you answer at a glance, while "what do I own?"
 * is one you read line by line.
 */
export function InvestmentsPage() {
  const { data: portfolio, isLoading } = usePortfolio();
  const { data: holdings } = useHoldings();
  const { data: history } = usePortfolioHistory(12);
  const { data: securities } = useSecurities();
  // Where a payment landed. Interest can be paid into any account, not only
  // the brokerage that holds the security — an MMF often sweeps to current.
  const { data: accounts } = useAccounts();
  const { activeWorkspace } = useAuth();

  const [tradeAction, setTradeAction] = useState<"buy" | "sell" | null>(null);
  const [showSecurity, setShowSecurity] = useState(false);
  const [showPrice, setShowPrice] = useState(false);
  const [showIncome, setShowIncome] = useState(false);

  const currency = portfolio?.currency ?? activeWorkspace?.tenant.base_currency ?? "USD";
  const hasSecurities = (securities?.length ?? 0) > 0;

  return (
    <>
      <PageHeader
        title="Investments"
        eyebrow={portfolio ? `${portfolio.holding_count} holdings` : undefined}
        description="What you hold, what it cost, and what it's worth today."
        actions={
          <Inline gap={2}>
            <Button variant="secondary" onClick={() => setShowSecurity(true)}>
              Add security
            </Button>
            {hasSecurities && (
              <Button variant="secondary" onClick={() => setShowPrice(true)}>
                Update prices
              </Button>
            )}
            <Button
              variant="primary"
              onClick={() => setTradeAction("buy")}
              disabled={!hasSecurities}
              icon={<Plus size={15} aria-hidden="true" />}
            >
              Record trade
            </Button>
          </Inline>
        }
      />

      {isLoading && <SkeletonCard />}

      {/* Two genuinely different empty states. Adding a security creates no
          holding, so the portfolio stays null — and showing "no investments
          tracked yet" at that point contradicts the workspace, which is
          exactly why re-adding the same symbol returned "already tracked". */}
      {!isLoading && !portfolio && !hasSecurities && (
        <Card>
          <EmptyState
            icon={TrendingUp}
            illustration="no-data"
            title="No investments tracked yet"
            body="Add a security and record a purchase to start tracking cost basis, gains and allocation."
            action={
              <Button variant="primary" onClick={() => setShowSecurity(true)} icon={<TagIcon size={15} aria-hidden="true" />}>
                Add your first security
              </Button>
            }
            tips={[
              "Every purchase posts to the ledger, so your portfolio reconciles against the cash that bought it.",
              "Cost basis is tracked per lot, so selling uses the right purchase price rather than an average.",
              "Record prices to see market value — unpriced holdings are counted at cost, never guessed.",
            ]}
          />
        </Card>
      )}

      {!isLoading && !portfolio && hasSecurities && (
        <Card>
          <EmptyState
            icon={TrendingUp}
            title="Ready for your first trade"
            body="These securities are tracked in this workspace. Record a purchase to start seeing cost basis, gains and allocation."
            action={
              <Button variant="primary" onClick={() => setTradeAction("buy")} icon={<Plus size={15} aria-hidden="true" />}>
                Record a trade
              </Button>
            }
          />
        </Card>
      )}

      {/* Always rendered when securities exist — with or without a portfolio.
          This is the acknowledgement that "add security" actually worked. */}
      {hasSecurities && (
        <div className="lf-dash-section">
          <Card
            title="Tracked securities"
            ruledHeader
            action={
              <Button variant="ghost" size="sm" onClick={() => setShowSecurity(true)}>
                Add another
              </Button>
            }
          >
            <SecuritiesTable securities={securities ?? []} />
          </Card>
        </div>
      )}

      {portfolio && (
        <>
          <div className="lf-dash-section">
            <Card prominence="primary">
              <PortfolioSummaryCard summary={portfolio} />
            </Card>
          </div>

          <div className="lf-dash-section">
            <Card title="Performance">
              <PerformanceChart points={history ?? []} currency={currency} />
            </Card>
          </div>

          <div className="lf-dash-section">
            <Grid cols={2} gap={4}>
              <Card>
                <AllocationChart
                  title="By asset class"
                  slices={portfolio.asset_allocation}
                  currency={currency}
                />
              </Card>
              <Card>
                <AllocationChart
                  title="By sector"
                  slices={portfolio.sector_allocation}
                  currency={currency}
                />
              </Card>
            </Grid>
          </div>

          <div className="lf-dash-section">
            <div className="lf-coach-feed-head">
              <h2 className="lf-section-title">Holdings</h2>
              <Inline gap={2}>
                <Button variant="secondary" size="sm" onClick={() => setTradeAction("buy")}>
                  Buy
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setTradeAction("sell")}
                  disabled={(holdings?.length ?? 0) === 0}
                >
                  Sell
                </Button>
                {/* Interest and dividends are how an MMF or a bond actually
                    pays you, so recording one sits with the other holding
                    actions rather than being buried elsewhere. */}
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setShowIncome(true)}
                  disabled={(holdings?.length ?? 0) === 0}
                >
                  Record payment
                </Button>
              </Inline>
            </div>
            <HoldingsTable holdings={holdings ?? []} />
          </div>
        </>
      )}

      <SecurityModal
        open={showSecurity}
        onClose={() => setShowSecurity(false)}
        defaultCurrency={currency}
      />
      <PriceModal open={showPrice} onClose={() => setShowPrice(false)} holdings={holdings ?? []} />
      <IncomeModal
        open={showIncome}
        onClose={() => setShowIncome(false)}
        holdings={holdings ?? []}
        accounts={accounts ?? []}
      />
      <TradeModal
        open={tradeAction !== null}
        action={tradeAction ?? "buy"}
        onClose={() => setTradeAction(null)}
        securities={securities ?? []}
        holdings={holdings ?? []}
      />
    </>
  );
}
