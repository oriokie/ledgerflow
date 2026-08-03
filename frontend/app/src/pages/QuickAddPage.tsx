import { Check, Sparkles } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAccounts } from "../hooks/useFinance";
import { usePendingQuickAddCount, useQuickAdd } from "../hooks/useQuickAdd";
import { majorToMinor } from "../lib/money";
import { Button, Card, Input, PageHeader, SegmentedControl, Stack, Text } from "../ui";
import { useToast } from "../ui/toastContext";

/**
 * Quick Add.
 *
 * Two required fields — amount and who it was to — because that is the
 * minimum a person can reliably enter in a queue, on a phone, without giving
 * up. Everything else (which account, which category) is inferred by the
 * backend and shown back rather than asked for up front; see
 * apps.finance.quick_add for what gets inferred and why.
 *
 * Works offline by design: the mutation queues the entry locally on a
 * genuine network failure and confirms "saved, will send" rather than losing
 * what was typed. See hooks/useQuickAdd.ts for the safety property this
 * depends on (an idempotency key the server guarantees is safe to replay).
 */
export function QuickAddPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const quickAdd = useQuickAdd();
  const pendingCount = usePendingQuickAddCount();

  const { data: accounts } = useAccounts();

  const [amount, setAmount] = useState("");
  const [merchant, setMerchant] = useState("");
  const [isIncome, setIsIncome] = useState(false);
  const [lastResult, setLastResult] = useState<{
    accountName: string;
    categoryName: string | null;
    categoryInferred: boolean;
  } | null>(null);

  const canSubmit = amount.trim() !== "" && Number(amount) > 0 && merchant.trim() !== "";

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;

    const amountMinor = majorToMinor(Number(amount));
    const outcome = await quickAdd.mutateAsync({ amountMinor, merchant: merchant.trim(), isIncome });

    if (outcome.queued) {
      toast("Saved — will send once you're back online.", { tone: "info" });
    } else if (outcome.result) {
      toast(`Added ${merchant.trim()}`, { tone: "success" });
      setLastResult({
        accountName: outcome.result.financial_account_name,
        categoryName: outcome.result.category_name,
        categoryInferred: outcome.result.category_was_inferred,
      });
    }

    setAmount("");
    setMerchant("");
  };

  const hasAnyAccount = (accounts?.length ?? 0) > 0;

  return (
    <>
      <PageHeader
        title="Quick Add"
        description="Two taps, one transaction. Everything else is filled in for you."
      />

      {!hasAnyAccount ? (
        <Card>
          <Text tone="secondary" size="sm">
            Add an account before using Quick Add.
          </Text>
        </Card>
      ) : (
        <Card>
          <form onSubmit={onSubmit} noValidate>
            <Stack gap={5}>
              <SegmentedControl
                legend="Type"
                options={[
                  { value: "expense", label: "Spent" },
                  { value: "income", label: "Received" },
                ]}
                value={isIncome ? "income" : "expense"}
                onChange={(value) => setIsIncome(value === "income")}
              />

              {/* Amount first: on a phone, the number is usually the thing
                  someone already has in mind before they've decided how to
                  describe the merchant. */}
              <Input
                label="Amount"
                required
                amount
                inputMode="decimal"
                placeholder="0.00"
                autoFocus
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
              />

              <Input
                label={isIncome ? "From" : "To"}
                required
                placeholder={isIncome ? "Employer, client…" : "Coffee shop, store…"}
                value={merchant}
                onChange={(event) => setMerchant(event.target.value)}
                hint="Whatever you'd call it — LedgerFlow tidies the name up."
              />

              <Button
                type="submit"
                variant="primary"
                size="lg"
                block
                loading={quickAdd.isPending}
                disabled={!canSubmit}
              >
                Add
              </Button>

              {pendingCount > 0 && (
                <Text tone="tertiary" size="xs">
                  {pendingCount} waiting to send once you're back online.
                </Text>
              )}
            </Stack>
          </form>
        </Card>
      )}

      {/* What was inferred, shown back rather than asked for up front — a
          user who typed one word and an amount deserves to see what was
          guessed on their behalf. */}
      {lastResult && (
        <Card>
          <div className="lf-quickadd-confirmation">
            <Check size={16} strokeWidth={2.4} aria-hidden="true" />
            <div>
              <Text size="sm">
                Added to <strong>{lastResult.accountName}</strong>
                {lastResult.categoryName && (
                  <>
                    {" "}
                    as <strong>{lastResult.categoryName}</strong>
                  </>
                )}
              </Text>
              {lastResult.categoryInferred && (
                <Text tone="tertiary" size="xs">
                  <Sparkles size={12} strokeWidth={2} aria-hidden="true" /> Category guessed from
                  past transactions —{" "}
                  <button
                    type="button"
                    className="lf-quickadd-fix-link"
                    onClick={() => navigate("/transactions")}
                  >
                    fix it
                  </button>{" "}
                  if that's wrong.
                </Text>
              )}
            </div>
          </div>
        </Card>
      )}
    </>
  );
}
