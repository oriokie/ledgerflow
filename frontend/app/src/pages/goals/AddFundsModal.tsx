import { ArrowRight, PiggyBank, Wallet } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { ApiError } from "../../api/client";
import type { SavingsGoal } from "../../api/types";
import { useAccounts } from "../../hooks/useFinance";
import { useContributeToGoal } from "../../hooks/useGoals";
import { formatAmount, majorToMinor } from "../../lib/money";
import { Banner, Button, Input, Modal, Select, Stack, Text } from "../../ui";

/** The two things "add funds" can mean. Keeping them as an explicit choice is
 * the whole point of this modal: the same £200 is a different fact depending
 * on whether the money has already moved. */
type Mode = "track" | "transfer";

/**
 * Add funds to a goal.
 *
 * The old inline quick-add could only ever record the first meaning — money
 * already set aside — which left "does this reduce my current account?"
 * unanswerable from the UI, and the honest answer (no) surprising. So the
 * question is now asked outright rather than assumed, and the modal states
 * the consequence of the chosen answer before the user commits.
 *
 * Transferring is only offered when there's somewhere for the money to go: a
 * goal with no linked account and no eligible destination can still be tracked,
 * it just can't be funded from here.
 */
export function AddFundsModal({
  open,
  onClose,
  goal,
  initialAmountMinor,
}: {
  open: boolean;
  onClose: () => void;
  goal: SavingsGoal;
  /** Pre-fill from a quick-add chip or the "amount to next milestone" nudge. */
  initialAmountMinor?: number;
}) {
  const contribute = useContributeToGoal();
  const { data: accounts } = useAccounts();
  const currency = goal.currency;

  const [mode, setMode] = useState<Mode>("track");
  const [amount, setAmount] = useState("");
  const [fromAccountId, setFromAccountId] = useState("");
  const [toAccountId, setToAccountId] = useState("");
  const [memo, setMemo] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Cross-currency funding needs an FX rate and a gain/loss posting, so the
  // backend refuses it. Filtering here means the user never picks an account
  // only to be told no.
  const eligible = useMemo(
    () => (accounts ?? []).filter((a) => a.currency === currency && !a.is_archived),
    [accounts, currency],
  );

  const destinationId = goal.linked_account_id ?? toAccountId;
  const linkedAccount = eligible.find((a) => a.id === goal.linked_account_id);
  const sources = eligible.filter((a) => a.id !== destinationId);
  const destinations = eligible.filter((a) => a.id !== fromAccountId);
  // Funding needs a real pair to move between. With a linked destination that
  // means one *other* account; without one it means two accounts, because
  // money cannot be transferred to where it already is.
  const canTransfer = goal.linked_account_id
    ? eligible.some((a) => a.id !== goal.linked_account_id)
    : eligible.length >= 2;

  const amountMinor = amount ? majorToMinor(Number(amount)) : (initialAmountMinor ?? 0);
  const sourceAccount = eligible.find((a) => a.id === fromAccountId);
  const overdraws = sourceAccount != null && amountMinor > sourceAccount.balance_minor;

  const reset = () => {
    setAmount("");
    setMemo("");
    setError(null);
    setMode("track");
    setFromAccountId("");
    setToAccountId("");
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!amountMinor || amountMinor <= 0) {
      setError("Enter an amount greater than zero.");
      return;
    }
    if (mode === "transfer" && !fromAccountId) {
      setError("Choose which account the money is coming from.");
      return;
    }
    if (mode === "transfer" && !goal.linked_account_id && !toAccountId) {
      setError("Choose which account the money is going to.");
      return;
    }

    try {
      await contribute.mutateAsync({
        goalId: goal.id,
        amountMinor,
        memo: memo || undefined,
        fromAccountId: mode === "transfer" ? fromAccountId : undefined,
        toAccountId: mode === "transfer" && !goal.linked_account_id ? toAccountId : undefined,
      });
      reset();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't add that contribution.");
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={`Add funds to ${goal.name}`}
      description="Record money you've already set aside, or move it now."
      footerStart={
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
      }
      footer={
        <Button variant="primary" onClick={submit} loading={contribute.isPending}>
          {mode === "transfer" ? "Transfer and add" : "Add funds"}
        </Button>
      }
    >
      <form onSubmit={submit} noValidate>
        <Stack gap={4}>
          <Input
            amount
            required
            type="number"
            step="0.01"
            min="0.01"
            label="Amount"
            placeholder="0.00"
            aria-label={`Amount to add to ${goal.name}`}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />

          <fieldset className="lf-fund-modes">
            <legend className="lf-field-label">Where's it coming from?</legend>

            <label className="lf-fund-mode" data-selected={mode === "track"}>
              <input
                type="radio"
                name="fund-mode"
                value="track"
                checked={mode === "track"}
                onChange={() => setMode("track")}
              />
              <PiggyBank size={18} aria-hidden="true" />
              <span>
                <span className="lf-fund-mode-title">I've already set it aside</span>
                <span className="lf-fund-mode-body">
                  Just track it against the goal. No balance changes.
                </span>
              </span>
            </label>

            <label
              className="lf-fund-mode"
              data-selected={mode === "transfer"}
              data-disabled={!canTransfer}
            >
              <input
                type="radio"
                name="fund-mode"
                value="transfer"
                checked={mode === "transfer"}
                disabled={!canTransfer}
                onChange={() => setMode("transfer")}
              />
              <Wallet size={18} aria-hidden="true" />
              <span>
                <span className="lf-fund-mode-title">Move the money now</span>
                <span className="lf-fund-mode-body">
                  {canTransfer
                    ? "Transfers out of an account you choose, reducing its balance."
                    : `Needs two ${currency} accounts to move between.`}
                </span>
              </span>
            </label>
          </fieldset>

          {mode === "transfer" && (
            <Stack gap={3}>
              <Select
                label="From"
                required
                value={fromAccountId}
                onChange={(e) => setFromAccountId(e.target.value)}
                options={[
                  { value: "", label: "Choose an account…" },
                  ...sources.map((a) => ({
                    value: a.id,
                    label: `${a.name} — ${formatAmount(a.balance_minor, a.currency)}`,
                  })),
                ]}
              />

              {goal.linked_account_id ? (
                <Text tone="tertiary" size="xs">
                  Going to {linkedAccount?.name ?? "the goal's linked account"}.
                </Text>
              ) : (
                <Select
                  label="To"
                  required
                  hint="This goal has no linked account, so pick where the money lands."
                  value={toAccountId}
                  onChange={(e) => setToAccountId(e.target.value)}
                  options={[
                    { value: "", label: "Choose an account…" },
                    ...destinations.map((a) => ({
                      value: a.id,
                      label: `${a.name} — ${formatAmount(a.balance_minor, a.currency)}`,
                    })),
                  ]}
                />
              )}

              {/* Not a blocker — an account can legitimately go negative, and
                  refusing would be us overruling the user about their own
                  money. Saying so plainly is enough. */}
              {overdraws && sourceAccount && (
                <Banner tone="warning">
                  That's more than {sourceAccount.name} holds (
                  {formatAmount(sourceAccount.balance_minor, currency)}). The transfer will still
                  post and leave it overdrawn.
                </Banner>
              )}
            </Stack>
          )}

          <Input
            label="Note"
            optional
            placeholder="What this is for"
            value={memo}
            onChange={(e) => setMemo(e.target.value)}
          />

          {/* Consequence, stated before the button rather than discovered after. */}
          {amountMinor > 0 && (
            <div className="lf-fund-preview">
              {mode === "transfer" && sourceAccount ? (
                <Text size="sm">
                  {sourceAccount.name} {formatAmount(sourceAccount.balance_minor, currency)}{" "}
                  <ArrowRight size={13} aria-hidden="true" />{" "}
                  <strong>{formatAmount(sourceAccount.balance_minor - amountMinor, currency)}</strong>
                  {" · "}
                  {goal.name} {formatAmount(goal.saved_minor, currency)}{" "}
                  <ArrowRight size={13} aria-hidden="true" />{" "}
                  <strong>{formatAmount(goal.saved_minor + amountMinor, currency)}</strong>
                </Text>
              ) : (
                <Text size="sm">
                  {goal.name} {formatAmount(goal.saved_minor, currency)}{" "}
                  <ArrowRight size={13} aria-hidden="true" />{" "}
                  <strong>{formatAmount(goal.saved_minor + amountMinor, currency)}</strong>
                  {" · no account balance changes"}
                </Text>
              )}
            </div>
          )}

          {error && <Banner tone="danger">{error}</Banner>}
        </Stack>
      </form>
    </Modal>
  );
}
