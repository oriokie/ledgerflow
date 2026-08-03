import { Plus } from "lucide-react";
import type { Wallet } from "../../api/types";
import { Badge, Button, Card, Grid, Money } from "../../ui";

/**
 * Wallets group accounts (e.g. "Household" vs "Business") and surface a rolled-up
 * balance per currency. Membership is managed from each account's detail panel.
 */
export function WalletsSection({
  wallets,
  onNewWallet,
}: {
  wallets: Wallet[] | undefined;
  onNewWallet: () => void;
}) {
  // An optional grouping feature nobody has used yet does not deserve more of
  // the page than the accounts themselves. Empty, it was a full-height card
  // with an icon, a heading, a paragraph and a button — taller than the real
  // account list beside it. One line offering the feature is the whole job.
  if (!wallets || wallets.length === 0) {
    return (
      <section className="lf-dash-section">
        <Button variant="ghost" size="sm" icon={<Plus size={15} strokeWidth={2} />} onClick={onNewWallet}>
          Group accounts into wallets
        </Button>
      </section>
    );
  }

  return (
    <section className="lf-dash-section">
      <div className="lf-section-head">
        <h2>Wallets</h2>
        <Button variant="ghost" size="sm" icon={<Plus size={15} strokeWidth={2} />} onClick={onNewWallet}>
          New wallet
        </Button>
      </div>

      <Grid cols={3} gap={4}>
        {wallets.map((wallet) => (
            <Card
              key={wallet.id}
              title={wallet.name}
              action={wallet.is_default ? <Badge tone="neutral">Default</Badge> : undefined}
            >
              {wallet.balances.length === 0 ? (
                <span className="lf-row-sub">No accounts assigned yet.</span>
              ) : (
                <div style={{ marginTop: "var(--lf-space-2)" }}>
                  {wallet.balances.map((b) => (
                    <div key={b.currency} className="lf-meter-row">
                      <span className="lf-row-sub">{b.currency}</span>
                      <Money amountMinor={b.balance_minor} currency={b.currency} neutral />
                    </div>
                  ))}
                </div>
              )}
            </Card>
          ))}
      </Grid>
    </section>
  );
}
