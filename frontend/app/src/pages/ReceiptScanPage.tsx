import { AlertTriangle, Receipt as ReceiptIcon, Sparkles } from "lucide-react";
import { useState } from "react";
import { ReceiptCamera } from "../components/receipts/ReceiptCamera";
import { useAccounts, useCategories } from "../hooks/useFinance";
import {
  useCaptureReceipt,
  useConfirmReceiptFields,
  useDiscardReceipt,
  useLinkReceipt,
  useReceipt,
} from "../hooks/useReceipts";
import { majorToMinor, minorToMajor } from "../lib/money";
import { Button, Card, EmptyState, Input, PageHeader, Select, Stack, Text } from "../ui";
import { useToast } from "../ui/toastContext";

/**
 * Scan a receipt, review what OCR read, confirm, and post.
 *
 * The governing rule this page exists to enforce visually as well as in the
 * backend: what OCR guessed is never what gets posted. Every field starts
 * pre-filled from the guess — that's the whole point of scanning instead of
 * typing — but every field is an editable input the user must actively
 * leave alone or change, never a fact presented as already true.
 */
export function ReceiptScanPage() {
  const toast = useToast();
  const [receiptId, setReceiptId] = useState<string | null>(null);
  const [showCamera, setShowCamera] = useState(true);

  const capture = useCaptureReceipt();
  const { data: receipt, isLoading } = useReceipt(receiptId);
  const confirmFields = useConfirmReceiptFields();
  const link = useLinkReceipt();
  const discard = useDiscardReceipt();

  const { data: accounts } = useAccounts();
  const { data: categories } = useCategories();

  const [merchant, setMerchant] = useState("");
  const [amount, setAmount] = useState("");
  const [occurredOn, setOccurredOn] = useState("");
  const [accountId, setAccountId] = useState("");
  const [categoryId, setCategoryId] = useState("");

  const onCaptured = async (file: Blob) => {
    setShowCamera(false);
    try {
      const created = await capture.mutateAsync(file);
      setReceiptId(created.id);
    } catch {
      toast("Couldn't upload that photo.", { tone: "info" });
      setShowCamera(true);
    }
  };

  // Pre-fill the confirmation form the moment OCR results land — a starting
  // point the user edits, never a value silently posted on their behalf.
  if (receipt && merchant === "" && amount === "" && receipt.status !== "pending_upload") {
    if (receipt.confirmed_merchant && merchant === "") setMerchant(receipt.confirmed_merchant);
    if (receipt.confirmed_amount_minor && amount === "")
      setAmount(String(minorToMajor(receipt.confirmed_amount_minor)));
    if (receipt.confirmed_occurred_on && occurredOn === "") setOccurredOn(receipt.confirmed_occurred_on);
  }

  const onLink = async () => {
    if (!receiptId || !accountId || !categoryId || !amount) return;
    await confirmFields.mutateAsync({
      receiptId,
      fields: {
        merchant,
        amountMinor: majorToMinor(Number(amount)),
        occurredOn: occurredOn || undefined,
      },
    });
    await link.mutateAsync({ receiptId, financialAccountId: accountId, categoryId });
    toast(`Added ${merchant || "receipt"}`, { tone: "success" });
    resetToCamera();
  };

  const onDiscard = async () => {
    if (receiptId) await discard.mutateAsync(receiptId);
    resetToCamera();
  };

  const resetToCamera = () => {
    setReceiptId(null);
    setMerchant("");
    setAmount("");
    setOccurredOn("");
    setAccountId("");
    setCategoryId("");
    setShowCamera(true);
  };

  if (showCamera) {
    return <ReceiptCamera onCapture={onCaptured} onClose={() => window.history.back()} />;
  }

  const processing = receipt?.status === "processing" || receipt?.status === "uploaded" || isLoading;
  const unreadable = receipt?.status === "unreadable" || receipt?.status === "failed";
  const readyToConfirm = receipt && !processing;

  return (
    <>
      <PageHeader title="Confirm receipt" description="Check what was read before it's added." />

      {processing && (
        <Card>
          <EmptyState icon={ReceiptIcon} title="Reading your receipt…" body="This only takes a moment." />
        </Card>
      )}

      {unreadable && (
        <Card>
          <div className="lf-receipt-unreadable">
            <AlertTriangle size={18} strokeWidth={2} aria-hidden="true" />
            <Text tone="secondary" size="sm">
              Couldn't read this one automatically — fill in the details by hand below.
            </Text>
          </div>
        </Card>
      )}

      {readyToConfirm && (
        <Card>
          <Stack gap={4}>
            {receipt.confidence > 0 && receipt.confidence < 0.7 && (
              <Text tone="tertiary" size="xs">
                <Sparkles size={12} strokeWidth={2} aria-hidden="true" /> Some of this may not be
                right — double-check before confirming.
              </Text>
            )}

            <Input
              label="Merchant"
              required
              value={merchant}
              onChange={(event) => setMerchant(event.target.value)}
            />
            <Input
              label="Amount"
              required
              amount
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
            <Input
              label="Date"
              type="date"
              value={occurredOn}
              onChange={(event) => setOccurredOn(event.target.value)}
            />
            <Select
              label="Account"
              required
              value={accountId}
              onChange={(event) => setAccountId(event.target.value)}
              options={(accounts ?? []).map((a) => ({ value: a.id, label: a.name }))}
              placeholder="Choose an account"
            />
            <Select
              label="Category"
              required
              value={categoryId}
              onChange={(event) => setCategoryId(event.target.value)}
              options={(categories ?? []).map((c) => ({ value: c.id, label: c.name }))}
              placeholder="Choose a category"
            />

            <div className="lf-receipt-actions">
              <Button variant="secondary" onClick={onDiscard}>
                Discard
              </Button>
              <Button
                variant="primary"
                onClick={onLink}
                loading={link.isPending || confirmFields.isPending}
                disabled={!merchant || !amount || !accountId || !categoryId}
              >
                Add transaction
              </Button>
            </div>
          </Stack>
        </Card>
      )}
    </>
  );
}
