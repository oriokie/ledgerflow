import { AlertTriangle, Receipt as ReceiptIcon, Sparkles } from "lucide-react";
import { useState } from "react";
import { ApiError } from "../api/client";
import { ReceiptCamera } from "../components/receipts/ReceiptCamera";
import { useAccounts, useCategories, useTransactions } from "../hooks/useFinance";
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
  // Whether account/category were filled in for the user rather than picked
  // by them — Quick Add's rule ("never silent") applies just as much to a
  // dropdown as to free text, so the hint disappears the moment they choose.
  const [accountGuessed, setAccountGuessed] = useState(false);
  const [categoryGuessed, setCategoryGuessed] = useState(false);

  const onCaptured = async (file: Blob) => {
    setShowCamera(false);
    try {
      const created = await capture.mutateAsync(file);
      setReceiptId(created.id);
    } catch {
      toast("Couldn't upload that photo.", { tone: "danger" });
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

  // Default the account to whichever one was used most recently — the same
  // "most likely still in the user's hand" signal Quick Add infers from
  // (apps.finance.quick_add._most_recently_used_account) — so confirming a
  // receipt doesn't ask a question Quick Add would have answered for free.
  const accountNeedsDefault = !!receiptId && accountId === "" && receipt?.status !== "pending_upload";
  // Only fetched when nothing better is already on the receipt itself.
  const { data: recentTxns } = useTransactions({}, accountNeedsDefault && !receipt?.financial_account_id);
  if (accountNeedsDefault && (receipt?.financial_account_id || recentTxns || accounts)) {
    const guess = receipt?.financial_account_id || recentTxns?.results[0]?.financial_account_id || accounts?.[0]?.id;
    if (guess) {
      setAccountId(guess);
      setAccountGuessed(true);
    }
  }

  // Default the category the same way Quick Add does — from what this
  // merchant was categorised as last time (the receipt already carries that
  // merchant name from OCR; no need to make the user type it again to get
  // the same signal Quick Add's suggest_category would give it).
  const merchantGuess = receipt?.confirmed_merchant ?? "";
  const categoryNeedsDefault = !!receiptId && categoryId === "" && merchantGuess !== "";
  // Only fetched when nothing better is already on the receipt itself.
  const { data: merchantMatches } = useTransactions(
    { search: merchantGuess },
    categoryNeedsDefault && !receipt?.confirmed_category_id,
  );
  if (categoryNeedsDefault && (receipt?.confirmed_category_id || merchantMatches)) {
    const guess =
      receipt?.confirmed_category_id || merchantMatches?.results.find((t) => t.category_id)?.category_id;
    if (guess) {
      setCategoryId(guess);
      setCategoryGuessed(true);
    }
  }

  const onLink = async () => {
    if (!receiptId || !accountId || !categoryId || !amount) return;
    try {
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
    } catch (err) {
      // Leave every field exactly as the user left it — they just filled in
      // four fields by hand and re-typing them on top of a failed request is
      // exactly the tax this fix exists to remove.
      toast(err instanceof ApiError ? err.detail : "Couldn't add that receipt — check the details and try again.", {
        tone: "danger",
      });
    }
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
    setAccountGuessed(false);
    setCategoryGuessed(false);
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
              onChange={(event) => {
                setAccountId(event.target.value);
                setAccountGuessed(false);
              }}
              options={(accounts ?? []).map((a) => ({ value: a.id, label: a.name }))}
              placeholder="Choose an account"
              hint={
                accountGuessed && (
                  <>
                    <Sparkles size={12} strokeWidth={2} aria-hidden="true" /> Guessed from your most
                    recent activity — change it if that's wrong.
                  </>
                )
              }
            />
            <Select
              label="Category"
              required
              value={categoryId}
              onChange={(event) => {
                setCategoryId(event.target.value);
                setCategoryGuessed(false);
              }}
              options={(categories ?? []).map((c) => ({ value: c.id, label: c.name }))}
              placeholder="Choose a category"
              hint={
                categoryGuessed && (
                  <>
                    <Sparkles size={12} strokeWidth={2} aria-hidden="true" /> Guessed from past
                    purchases at this merchant — change it if that's wrong.
                  </>
                )
              }
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
