import { useState } from "react";
import { ApiError } from "../../api/client";
import type { Transaction } from "../../api/types";
import {
  useAccounts,
  useCategories,
  useCreatePayee,
  usePayees,
  useReclassifyTransfer,
  useSetTransactionTags,
  useSplitTransaction,
  useTags,
  useUpdateTransaction,
  useVoidTransaction,
} from "../../hooks/useFinance";
import { majorToMinor } from "../../lib/money";
import { Badge, Banner, Button, Chip, ConfirmAction, Divider, Grid, Inline, Input, Modal, Money, Select, Stack, Text } from "../../ui";
import { ReceiptManager } from "./ReceiptManager";

export function TransactionDetail({ txn, onClose }: { txn: Transaction; onClose: () => void }) {
  const { data: categories } = useCategories();
  const { data: payees } = usePayees();
  const { data: tags } = useTags();
  const { data: accounts } = useAccounts();
  const updateTxn = useUpdateTransaction();
  const voidTxn = useVoidTransaction();
  const splitTxn = useSplitTransaction();
  const setTags = useSetTransactionTags();
  const reclassifyTransfer = useReclassifyTransfer();
  const createPayee = useCreatePayee();

  const [memo, setMemo] = useState(txn.memo);
  const [categoryId, setCategoryId] = useState(txn.category_id ?? "");
  const [payeeId, setPayeeId] = useState(txn.payee_id ?? "");
  const [addingPayee, setAddingPayee] = useState(false);
  const [newPayeeName, setNewPayeeName] = useState("");
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set());
  const [splitting, setSplitting] = useState(false);
  const [parts, setParts] = useState([
    { category_id: "", amount: "" },
    { category_id: "", amount: "" },
  ]);
  const [allocatingTransfer, setAllocatingTransfer] = useState(false);
  const [counterAccountId, setCounterAccountId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const isTransfer = !!txn.transfer_group;
  const isExpense = txn.amount_minor < 0 && !isTransfer;
  const expenseCategories = categories?.filter((c) => c.kind === "expense") ?? [];
  const usableCategories = categories?.filter((c) => c.kind === (txn.amount_minor < 0 ? "expense" : "income")) ?? [];

  const save = async () => {
    setError(null);
    try {
      await updateTxn.mutateAsync({
        txnId: txn.id,
        payload: { memo, category_id: categoryId || null, payee_id: payeeId || null },
      });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't save changes.");
    }
  };

  const addPayee = async () => {
    if (!newPayeeName.trim()) return;
    setError(null);
    try {
      const created = await createPayee.mutateAsync({ name: newPayeeName.trim() });
      setPayeeId(created.id);
      setNewPayeeName("");
      setAddingPayee(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't create the payee.");
    }
  };

  const applyTags = async () => {
    setError(null);
    try {
      await setTags.mutateAsync({ txnId: txn.id, tagIds: [...selectedTags] });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't update tags.");
    }
  };

  const doVoid = async () => {
    setError(null);
    try {
      await voidTxn.mutateAsync(txn.id);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't void this transaction.");
    }
  };

  const doSplit = async () => {
    setError(null);
    const cleaned = parts
      .filter((p) => p.category_id && p.amount)
      .map((p) => ({ category_id: p.category_id, amount_minor: majorToMinor(Number(p.amount)) }));
    if (cleaned.length < 2) return setError("A split needs at least two parts.");
    try {
      await splitTxn.mutateAsync({ txnId: txn.id, parts: cleaned });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't split — parts must sum to the original amount.");
    }
  };

  const doAllocateTransfer = async () => {
    setError(null);
    if (!counterAccountId) return setError("Choose the other account this money moved to or from.");
    try {
      await reclassifyTransfer.mutateAsync({ txnId: txn.id, counterAccountId });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't allocate this as a transfer.");
    }
  };

  return (
    <Modal open onClose={onClose} title="Transaction" size="lg">
      <div className="lf-card-header" style={{ marginBottom: "var(--lf-space-3)" }}>
        <Money amountMinor={txn.amount_minor} currency={txn.currency} isTransfer={isTransfer} hero />
        <Badge tone="neutral">{txn.status}</Badge>
      </div>
      <Text tone="secondary" size="sm">
        {new Date(txn.occurred_at).toLocaleString()}
      </Text>

      {!isTransfer && (
        <>
          <Grid cols={3} gap={4} style={{ marginTop: "var(--lf-space-4)" }}>
            <Select
              label="Category"
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value)}
              options={[{ value: "", label: "Uncategorized" }, ...usableCategories.map((c) => ({ value: c.id, label: c.name }))]}
            />
            <div>
              <Select
                label="Payee"
                value={payeeId}
                onChange={(e) => setPayeeId(e.target.value)}
                placeholder="No payee"
                options={(payees ?? []).map((p) => ({ value: p.id, label: p.name }))}
              />
              {!addingPayee ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setAddingPayee(true)}
                  style={{ marginTop: "var(--lf-space-1)" }}
                >
                  + New payee
                </Button>
              ) : (
                <Inline gap={2} wrap={false} style={{ marginTop: "var(--lf-space-1)" }}>
                  <Input
                    aria-label="New payee name"
                    placeholder="Payee name"
                    value={newPayeeName}
                    onChange={(e) => setNewPayeeName(e.target.value)}
                  />
                  <Button variant="secondary" size="sm" onClick={addPayee} loading={createPayee.isPending}>
                    Add
                  </Button>
                </Inline>
              )}
            </div>
            <Input label="Memo" value={memo} onChange={(e) => setMemo(e.target.value)} />
          </Grid>
          <Button variant="primary" onClick={save} loading={updateTxn.isPending}>
            Save changes
          </Button>
        </>
      )}

      {tags && tags.length > 0 && !isTransfer && (
        <div style={{ marginTop: "var(--lf-space-5)" }}>
          <p className="lf-label">Tags</p>
          <Inline gap={2} style={{ marginBottom: "var(--lf-space-2)" }}>
            {tags.map((tag) => (
              <Chip
                key={tag.id}
                active={selectedTags.has(tag.id)}
                onClick={() =>
                  setSelectedTags((prev) => {
                    const next = new Set(prev);
                    if (next.has(tag.id)) next.delete(tag.id);
                    else next.add(tag.id);
                    return next;
                  })
                }
              >
                {tag.name}
              </Chip>
            ))}
          </Inline>
          <Button variant="secondary" onClick={applyTags} loading={setTags.isPending}>
            Apply tags
          </Button>
        </div>
      )}

      <div style={{ marginTop: "var(--lf-space-5)" }}>
        <ReceiptManager txnId={txn.id} />
      </div>

      {isExpense && txn.status === "posted" && (
        <div style={{ marginTop: "var(--lf-space-5)" }}>
          {!splitting ? (
            <Button variant="ghost" onClick={() => setSplitting(true)}>
              Split across categories…
            </Button>
          ) : (
            <div>
              <p className="lf-label">Split this expense (parts must sum to the total)</p>
              <Stack gap={2}>
                {parts.map((part, i) => (
                  <Inline key={i} gap={2} wrap={false}>
                    <select
                      className="lf-select"
                      aria-label={`Part ${i + 1} category`}
                      value={part.category_id}
                      onChange={(e) =>
                        setParts((prev) => prev.map((p, j) => (j === i ? { ...p, category_id: e.target.value } : p)))
                      }
                    >
                      <option value="">Category…</option>
                      {expenseCategories.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                    <input
                      className="lf-input lf-input--amount"
                      aria-label={`Part ${i + 1} amount`}
                      type="number"
                      step="0.01"
                      min="0.01"
                      placeholder="0.00"
                      value={part.amount}
                      onChange={(e) =>
                        setParts((prev) => prev.map((p, j) => (j === i ? { ...p, amount: e.target.value } : p)))
                      }
                    />
                  </Inline>
                ))}
              </Stack>
              <Inline gap={2} style={{ marginTop: "var(--lf-space-2)" }}>
                <Button variant="ghost" onClick={() => setParts((prev) => [...prev, { category_id: "", amount: "" }])}>
                  + Part
                </Button>
                <Button variant="primary" onClick={doSplit} loading={splitTxn.isPending}>
                  Split
                </Button>
              </Inline>
            </div>
          )}
        </div>
      )}

      {!isTransfer && txn.status === "posted" && (
        <div style={{ marginTop: "var(--lf-space-5)" }}>
          {!allocatingTransfer ? (
            <Button
              variant="ghost"
              onClick={() => setAllocatingTransfer(true)}
              disabled={!!txn.split_group}
              title={
                txn.split_group
                  ? "This is part of a split — void the split and re-enter it first."
                  : txn.reconciled_at
                    ? "Un-reconcile this transaction first."
                    : undefined
              }
            >
              Allocate as transfer…
            </Button>
          ) : (
            <div>
              <p className="lf-label">
                Move money between your own accounts, not {txn.amount_minor > 0 ? "income" : "spending"}
              </p>
              <Text tone="tertiary" size="sm" style={{ marginBottom: "var(--lf-space-2)" }}>
                {txn.amount_minor > 0
                  ? "Which account did this money actually come from?"
                  : "Which account did this money actually go to?"}
              </Text>
              <Inline gap={2} wrap={false}>
                <Select
                  aria-label="Other account"
                  value={counterAccountId}
                  onChange={(e) => setCounterAccountId(e.target.value)}
                  placeholder="Choose account…"
                  options={(accounts ?? [])
                    .filter((a) => a.id !== txn.financial_account_id)
                    .map((a) => ({ value: a.id, label: a.name }))}
                />
                <Button variant="primary" onClick={doAllocateTransfer} loading={reclassifyTransfer.isPending}>
                  Allocate
                </Button>
              </Inline>
            </div>
          )}
        </div>
      )}

      {txn.status === "posted" && (
        <div style={{ marginTop: "var(--lf-space-5)" }}>
          <Divider />
          <ConfirmAction label="Void transaction" confirmLabel="Void" cancelLabel="Keep" onConfirm={doVoid} />
          <Text tone="tertiary" size="sm" style={{ marginTop: "var(--lf-space-2)" }}>
            Voiding reverses the posting in the ledger; history is preserved.
          </Text>
        </div>
      )}

      {error && <Banner tone="danger">{error}</Banner>}
    </Modal>
  );
}
