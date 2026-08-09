import { useState } from "react";
import { ApiError } from "../../api/client";
import type { FinancialAccount } from "../../api/types";
import { useUpdateAccount } from "../../hooks/useFinance";
import { Banner, Button, Checkbox, Input, Modal, Stack, Textarea } from "../../ui";

/** Edit-only, not a reuse of the "New account" form — that form also collects
 * currency/account_type, which are immutable once posted against. */
export function EditAccountModal({ account, onClose }: { account: FinancialAccount; onClose: () => void }) {
  const updateAccount = useUpdateAccount();
  const [name, setName] = useState(account.name);
  const [mask, setMask] = useState(account.mask ?? "");
  const [notes, setNotes] = useState(account.notes ?? "");
  const [isHidden, setIsHidden] = useState(!!account.is_hidden);
  const [includeInNetWorth, setIncludeInNetWorth] = useState(account.include_in_net_worth ?? true);
  const [includeInBudgets, setIncludeInBudgets] = useState(account.include_in_budgets ?? true);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    if (!name.trim()) return setError("Name can't be empty.");
    if (mask && !/^\d{4}$/.test(mask)) return setError("Last 4 digits must be four digits, or left blank.");
    try {
      await updateAccount.mutateAsync({
        accountId: account.id,
        payload: {
          name: name.trim(),
          mask,
          notes,
          is_hidden: isHidden,
          include_in_net_worth: includeInNetWorth,
          include_in_budgets: includeInBudgets,
        },
      });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't save changes.");
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Edit account"
      footerStart={
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
      }
      footer={
        <Button variant="primary" onClick={save} loading={updateAccount.isPending}>
          Save changes
        </Button>
      }
    >
      <Stack gap={4}>
        <Input label="Account name" value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
        <Input
          label="Last 4 digits"
          optional
          placeholder="4321"
          inputMode="numeric"
          maxLength={4}
          value={mask}
          onChange={(e) => setMask(e.target.value)}
        />
        <Textarea label="Notes" optional value={notes} onChange={(e) => setNotes(e.target.value)} />
        <Checkbox
          label="Hidden from summaries"
          checked={isHidden}
          onChange={(e) => setIsHidden(e.target.checked)}
        />
        <Checkbox
          label="Included in net worth"
          checked={includeInNetWorth}
          onChange={(e) => setIncludeInNetWorth(e.target.checked)}
        />
        <Checkbox
          label="Included in budgets"
          checked={includeInBudgets}
          onChange={(e) => setIncludeInBudgets(e.target.checked)}
        />
        {error && <Banner tone="danger">{error}</Banner>}
      </Stack>
    </Modal>
  );
}
