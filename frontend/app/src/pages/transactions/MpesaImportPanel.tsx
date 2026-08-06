import { useState } from "react";
import { ApiError } from "../../api/client";
import type { MpesaImportQueued, MpesaPreview } from "../../api/finance";
import { useAccounts, useImportMpesaStatement, usePreviewMpesaStatement } from "../../hooks/useFinance";
import { AlertTriangle, CheckCircle2, HelpCircle } from "lucide-react";
import { Banner, Button, Input, Select, Stack, Table, Text } from "../../ui";

/** Human labels for the transaction kinds the parser reports. Safaricom's own
 *  wording ("Merchant Payment Online") describes the rail; people think in
 *  terms of what they did. */
const KIND_LABELS: Record<string, string> = {
  send_money: "Sent to people",
  receive: "Received",
  paybill: "Paybill",
  buy_goods: "Till / Buy Goods",
  airtime: "Airtime & data",
  agent_withdrawal: "Agent withdrawals",
  agent_deposit: "Agent deposits",
  salary: "Salary",
  charge: "M-Pesa charges",
  overdraft_advance: "Fuliza borrowed",
  overdraft_repayment: "Fuliza repaid",
  reversal: "Reversals",
  other: "Other",
};

const money = (minor: number) =>
  (minor / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/**
 * How many rows a chosen date window covers, from the preview's per-day counts.
 *
 * Exported because this is the part worth testing on its own: both bounds are
 * inclusive, an empty bound means "unbounded" rather than any particular date,
 * and the comparison is lexicographic on YYYY-MM-DD — which is only correct
 * because that format sorts the same way as the dates it represents. The button
 * shows this number, so an off-by-one here is a promise the import then breaks.
 */
export function countInWindow(
  byDay: Record<string, number>,
  from: string,
  to: string,
): number {
  return Object.entries(byDay).reduce(
    (n, [day, count]) => ((!from || day >= from) && (!to || day <= to) ? n + count : n),
    0,
  );
}

/**
 * Two steps, and the split is deliberate.
 *
 * A statement is hundreds of rows covering months of someone's life. Importing
 * it is not a thing to do on trust and then inspect afterwards — so the first
 * step parses the file and shows what is in it, including whether the parsed
 * totals match the totals Safaricom printed on the statement itself. Only then
 * is there a button that writes anything.
 */
export function MpesaImportPanel() {
  const { data: accounts } = useAccounts();
  const preview = usePreviewMpesaStatement();
  const runImport = useImportMpesaStatement();

  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [accountId, setAccountId] = useState("");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [parsed, setParsed] = useState<MpesaPreview | null>(null);
  const [result, setResult] = useState<MpesaImportQueued | null>(null);
  const [error, setError] = useState<string | null>(null);

  // M-Pesa is shillings. Offering a dollar account would invite an import that
  // is wrong by a factor of ~130 and looks entirely plausible on screen.
  const kesAccounts = accounts?.filter((a) => a.currency === "KES") ?? [];

  const inRange = parsed === null ? null : countInWindow(parsed.by_day, fromDate, toDate);

  const onCheck = async () => {
    if (!file) return setError("Choose the statement PDF first.");
    setError(null);
    setResult(null);
    try {
      const p = await preview.mutateAsync({ file, password });
      setParsed(p);
      // Default to the statement's own span, so the fields read as "all of it"
      // rather than as empty boxes the user has to decode.
      if (p.first_seen) setFromDate(p.first_seen.slice(0, 10));
      if (p.last_seen) setToDate(p.last_seen.slice(0, 10));
    } catch (err) {
      setParsed(null);
      setError(err instanceof ApiError ? err.detail : "Could not read that statement.");
    }
  };

  const onImport = async () => {
    if (!file || !accountId) return setError("Choose an account to import into.");
    if (fromDate && toDate && fromDate > toDate) {
      return setError("The start date is after the end date.");
    }
    setError(null);
    try {
      setResult(await runImport.mutateAsync({ accountId, file, password, fromDate, toDate }));
      setParsed(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Import failed.");
    }
  };

  if (result) return <MpesaResult result={result} />;

  return (
    <Stack gap={4}>
      <Text tone="tertiary" size="sm">
        The PDF Safaricom emails you, with the password they sent with it. Fuliza is recorded as borrowing rather
        than income, and re-importing an overlapping statement is safe — nothing posts twice.
      </Text>

      <Input
        label="M-Pesa statement (PDF)"
        type="file"
        accept="application/pdf,.pdf"
        onChange={(e) => {
          setFile(e.target.files?.[0] ?? null);
          setParsed(null);
        }}
      />
      <Input
        label="Statement password"
        type="password"
        value={password}
        autoComplete="off"
        placeholder="From Safaricom's email"
        onChange={(e) => setPassword(e.target.value)}
        hint="Used to open the file and then discarded. It is never stored."
      />

      {!parsed && (
        <Button onClick={onCheck} loading={preview.isPending} disabled={!file}>
          Check statement
        </Button>
      )}

      {parsed && <PreviewSummary parsed={parsed} />}

      {parsed && (
        <>
          <Select label="Import into" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            <option value="">Select a KES account…</option>
            {kesAccounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
          {kesAccounts.length === 0 && (
            <Banner tone="warning">
              You have no account in KES. Create one first — M-Pesa statements are in shillings.
            </Banner>
          )}

          {/* The window matters more than it looks. Re-importing the same
              statement is already safe, but a transaction typed in by hand
              carries no statement id, so nothing can match it against a
              statement row — and a period tracked both ways is counted twice. */}
          <div className="lf-field-row">
            <Input
              label="Import from"
              type="date"
              value={fromDate}
              min={parsed.first_seen?.slice(0, 10)}
              max={parsed.last_seen?.slice(0, 10)}
              onChange={(e) => setFromDate(e.target.value)}
            />
            <Input
              label="Import until"
              type="date"
              value={toDate}
              min={parsed.first_seen?.slice(0, 10)}
              max={parsed.last_seen?.slice(0, 10)}
              onChange={(e) => setToDate(e.target.value)}
            />
          </div>
          <Text tone="tertiary" size="xs">
            Defaults to the whole statement. If you have already been recording this account by
            hand, start the day after your last manual entry — importing a period you have already
            tracked records it twice, and the importer cannot tell the two apart.
          </Text>

          <Button
            onClick={onImport}
            loading={runImport.isPending}
            disabled={!accountId || inRange === 0}
          >
            Import {inRange ?? parsed.rows_found} transaction{(inRange ?? parsed.rows_found) === 1 ? "" : "s"}
          </Button>
          {inRange === 0 && (
            <Text tone="tertiary" size="xs">
              No transactions fall inside those dates.
            </Text>
          )}
        </>
      )}

      {error && <Banner tone="danger">{error}</Banner>}
    </Stack>
  );
}

function PreviewSummary({ parsed }: { parsed: MpesaPreview }) {
  const kinds = Object.entries(parsed.by_kind).sort((a, b) => b[1].count - a[1].count);
  const fuliza = parsed.by_kind.overdraft_advance;

  return (
    <Stack gap={3}>
      <div className="lf-insight">
        <p className="lf-insight-title">
          {parsed.rows_found} transactions · {parsed.period_start} – {parsed.period_end}
        </p>
        <p className="lf-insight-body">
          In {money(parsed.paid_in_minor)} · out {money(parsed.withdrawn_minor)}
        </p>
      </div>

      {/* Three states, not two. An unverifiable statement must not render as a
          verified one just because nothing failed. */}
      {parsed.reconciles === true && (
        <div className="lf-insight lf-insight--good">
          <p className="lf-insight-title">
            <CheckCircle2 size={15} strokeWidth={1.8} aria-hidden="true" /> Totals match the statement
          </p>
          <p className="lf-insight-body">Every row was read — the figures add up to Safaricom's own totals.</p>
        </div>
      )}
      {parsed.reconciles === false && (
        <Banner tone="danger">
          <strong>Some rows could not be read.</strong> {parsed.discrepancy}. Importing now would leave your books
          short. Please send this statement to support rather than importing it.
        </Banner>
      )}
      {parsed.reconciles === null && (
        <div className="lf-insight">
          <p className="lf-insight-title">
            <HelpCircle size={15} strokeWidth={1.8} aria-hidden="true" /> Totals could not be checked
          </p>
          <p className="lf-insight-body">
            This statement did not print summary totals, so there is nothing to verify the parse against.
          </p>
        </div>
      )}

      {fuliza && fuliza.count > 0 && (
        <div className="lf-insight">
          <p className="lf-insight-title">
            <AlertTriangle size={15} strokeWidth={1.8} aria-hidden="true" /> Fuliza found —{" "}
            {money(Math.abs(fuliza.total_minor))} borrowed
          </p>
          <p className="lf-insight-body">
            This is an overdraft, so it will be recorded against a Fuliza credit line rather than counted as
            income. What you spent with it still counts as spending.
          </p>
        </div>
      )}

      <Table
        caption="What the statement contains, by transaction type"
        rows={kinds.map(([kind, v]) => ({ kind, ...v }))}
        rowKey={(r) => r.kind}
        columns={[
          { key: "kind", header: "Type", render: (r) => KIND_LABELS[r.kind] ?? r.kind },
          { key: "count", header: "Count", align: "right", render: (r) => r.count },
          {
            key: "total",
            header: "Total",
            align: "right",
            render: (r) => money(Math.abs(r.total_minor)),
          },
        ]}
      />
    </Stack>
  );
}

function MpesaResult({ result }: { result: MpesaImportQueued }) {
  return (
    <Stack gap={3}>
      <div className="lf-insight lf-insight--good">
        <p className="lf-insight-title">
          {result.rows_found} transactions are being imported
        </p>
        <p className="lf-insight-body">
          {result.detail} Fuliza is recorded as borrowing rather than income, and anything you
          have already imported is skipped.
        </p>
      </div>

      {/* Reconciliation is known before the work runs, because parsing happened
          in the request. So the one thing the user most needs to hear — "we
          read your whole statement correctly" — does not have to wait. */}
      {result.reconciles === true && (
        <Text tone="tertiary" size="xs">
          The totals matched the statement, so every row was read.
        </Text>
      )}
      {result.reconciles === false && (
        <Banner tone="danger">
          <strong>Some rows could not be read.</strong> {result.discrepancy}. Please send this
          statement to support rather than relying on the import.
        </Banner>
      )}
      {result.reconciles === null && (
        <Text tone="tertiary" size="xs">
          This statement printed no totals, so there was nothing to verify the parse against.
        </Text>
      )}
    </Stack>
  );
}
