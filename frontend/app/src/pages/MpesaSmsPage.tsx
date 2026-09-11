import { ClipboardPaste, Smartphone } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/client";
import { useCategories, useUpdateTransaction } from "../hooks/useFinance";
import { useOpenOnParam } from "../hooks/useOpenOnParam";
import { useCaptureMpesaSms, useMpesaSmsCaptures } from "../hooks/useMpesaSms";
import { formatMpesaWhen, parseMpesaSms } from "../lib/parseMpesaSms";
import { Banner, Button, Card, Input, Money, PageHeader, Select, Stack, Table, Text, Textarea } from "../ui";
import { useToast } from "../ui/toastContext";

const PLACEHOLDER =
  "UI94368KUX Confirmed. Ksh250.00 sent to JOHN NDUNGU 0707750700 on 9/9/26 at 3:29 PM…";

/**
 * Fast capture from the confirmation SMS Safaricom sends.
 *
 * Paste is the whole interaction: the receipt, date and amount are read from
 * the message, optional purpose/category can wait, and save posts against the
 * workspace's M-Pesa account. A later statement import skips these receipts
 * instead of recording them twice.
 */
export function MpesaSmsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const capture = useCaptureMpesaSms();
  const { data: captures } = useMpesaSmsCaptures();
  const { data: categories } = useCategories();
  const updateTxn = useUpdateTransaction();

  const [message, setMessage] = useState("");
  const [purpose, setPurpose] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [purposeTouched, setPurposeTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useOpenOnParam();

  const parsed = useMemo(() => parseMpesaSms(message), [message]);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!purposeTouched) setPurpose(parsed?.counterparty ?? "");
  }, [parsed?.counterparty, purposeTouched]);

  const expenseCategories = (categories ?? []).filter((c) => c.kind === "expense");
  const incomeCategories = (categories ?? []).filter((c) => c.kind === "income");
  const categoryOptions = parsed?.amountMinor && parsed.amountMinor > 0 ? incomeCategories : expenseCategories;

  const onPasteClipboard = async () => {
    setError(null);
    try {
      const text = await navigator.clipboard.readText();
      if (!text.trim()) {
        textareaRef.current?.focus();
        return;
      }
      applyMessage(text);
    } catch {
      textareaRef.current?.focus();
      toast("Paste into the box — the phone's share sheet is more reliable than the clipboard here.", {
        tone: "info",
      });
    }
  };

  const applyMessage = (text: string) => {
    setMessage(text);
    setPurposeTouched(false);
    setError(null);
  };

  const onSave = async () => {
    if (!parsed) {
      setError("Paste a full M-Pesa confirmation, starting with the receipt code.");
      return;
    }
    setError(null);
    try {
      const result = await capture.mutateAsync({
        message,
        purpose: purpose.trim(),
        categoryId: categoryId || null,
      });
      toast(
        result.already_recorded
          ? `Already in the books — ${result.receipt}`
          : `Saved ${result.receipt} to ${result.account_name}`,
        { tone: "success" },
      );
      setMessage("");
      setPurpose("");
      setCategoryId("");
      setPurposeTouched(false);
      textareaRef.current?.focus();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't save that message.");
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Capture"
        title="M-Pesa SMS"
        description="Paste the confirmation. The receipt, date and amount are read for you — purpose and category can wait."
        illustration="steps"
      />

      <Card prominence="primary">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void onSave();
          }}
          noValidate
        >
          <Stack gap={4}>
            <Textarea
              ref={textareaRef}
              label="M-Pesa message"
              required
              rows={5}
              className="lf-mpesa-sms-paste"
              placeholder={PLACEHOLDER}
              value={message}
              autoComplete="off"
              autoCorrect="off"
              spellCheck={false}
              enterKeyHint="done"
              onChange={(event) => applyMessage(event.target.value)}
              onKeyDown={(event) => {
                if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                  event.preventDefault();
                  void onSave();
                }
              }}
              hint="Copy the SMS from M-Pesa and paste it here. Saving deducts it from your M-Pesa account."
            />

            <Button type="button" variant="secondary" icon={<ClipboardPaste size={16} />} onClick={() => void onPasteClipboard()}>
              Paste from clipboard
            </Button>

            {parsed && (
              <dl className="lf-mpesa-sms-facts">
                <div className="lf-mpesa-sms-fact">
                  <dt>Receipt</dt>
                  <dd>{parsed.receipt}</dd>
                </div>
                <div className="lf-mpesa-sms-fact">
                  <dt>Amount</dt>
                  <dd>
                    <Money amountMinor={parsed.amountMinor} currency="KES" />
                  </dd>
                </div>
                <div className="lf-mpesa-sms-fact">
                  <dt>When</dt>
                  <dd>{formatMpesaWhen(parsed.occurredAt)}</dd>
                </div>
                <div className="lf-mpesa-sms-fact">
                  <dt>{parsed.amountMinor > 0 ? "From" : "To"}</dt>
                  <dd>{parsed.counterparty || "—"}</dd>
                </div>
              </dl>
            )}

            {parsed && parsed.chargeMinor > 0 && (
              <Text tone="tertiary" size="xs">
                Fee {formatKes(parsed.chargeMinor)} will be recorded as an M-Pesa charge.
              </Text>
            )}

            <Input
              label="Purpose"
              optional
              placeholder="Fare, shopping, rent…"
              value={purpose}
              onChange={(event) => {
                setPurposeTouched(true);
                setPurpose(event.target.value);
              }}
            />

            <Select
              label="Category"
              optional
              value={categoryId}
              onChange={(event) => setCategoryId(event.target.value)}
              hint="Skip this if you're in a hurry — you can categorise it later."
            >
              <option value="">Add later</option>
              {categoryOptions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              block
              loading={capture.isPending}
              disabled={!parsed}
              icon={<Smartphone size={18} />}
            >
              Save to M-Pesa
            </Button>

            {error && <Banner tone="danger">{error}</Banner>}
          </Stack>
        </form>
      </Card>

      {(captures?.length ?? 0) > 0 && (
        <Card title="Captured" ruledHeader>
          <Table
            caption="M-Pesa confirmations already entered"
            responsive
            compact
            rows={captures ?? []}
            rowKey={(row) => row.id}
            columns={[
              { key: "receipt", header: "Receipt", render: (row) => row.receipt },
              {
                key: "when",
                header: "Date",
                hideMobile: true,
                render: (row) => formatMpesaWhen(row.occurred_at),
              },
              {
                key: "purpose",
                header: "Purpose",
                render: (row) => row.purpose || row.counterparty || "—",
              },
              {
                key: "amount",
                header: "Amount",
                align: "right",
                render: (row) => <Money amountMinor={row.amount_minor} currency={row.currency} />,
              },
              {
                key: "category",
                header: "Category",
                render: (row) => (
                  <select
                    className="lf-select"
                    aria-label={`Category for ${row.receipt}`}
                    value={row.category_id ?? ""}
                    onChange={(event) => {
                      const next = event.target.value || null;
                      updateTxn.mutate(
                        { txnId: row.id, payload: { category_id: next } },
                        { onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mpesa-sms"] }) },
                      );
                    }}
                  >
                    <option value="">Uncategorized</option>
                    {(row.is_inflow ? incomeCategories : expenseCategories).map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                ),
              },
              {
                key: "status",
                header: "Statement",
                hideMobile: true,
                render: (row) => (row.already_on_statement ? "On statement" : "Pending import"),
              },
            ]}
          />
        </Card>
      )}
    </>
  );
}

function formatKes(minor: number): string {
  return `Ksh${(minor / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
