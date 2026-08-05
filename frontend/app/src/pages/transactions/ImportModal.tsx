import { useState } from "react";
import { ApiError } from "../../api/client";
import { financeExtendedApi } from "../../api/finance";
import { useAccounts, useImportTransactionsCsv } from "../../hooks/useFinance";
import { Download } from "lucide-react";
import { Banner, Button, Input, Modal, Select, Stack, Text } from "../../ui";

export function ImportModal({ onClose }: { onClose: () => void }) {
  const [downloading, setDownloading] = useState(false);

  /* Fetched rather than linked, because the endpoint is tenant-scoped and
     needs the auth header a bare <a href> cannot carry. */
  const downloadTemplate = async () => {
    setDownloading(true);
    try {
      const blob = await financeExtendedApi.importTemplate();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "ledgerflow-import-template.csv";
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(false);
    }
  };

  const { data: accounts } = useAccounts();
  const importCsv = useImportTransactionsCsv();
  const [accountId, setAccountId] = useState("");
  const [result, setResult] = useState<{
    imported: number;
    skipped_duplicate: number;
    errors: { line: number; error: string }[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onFile = async (file: File) => {
    if (!accountId) return setError("Choose an account first.");
    setError(null);
    const content = await file.text();
    try {
      setResult(await importCsv.mutateAsync({ accountId, content }));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Import failed.");
    }
  };

  return (
    <Modal open onClose={onClose} title="Import transactions (CSV)">
      <Stack gap={4}>
        <Text tone="tertiary" size="sm">
          Needs date, amount, and description columns (most bank exports work). Re-importing the same file is safe —
          duplicates are skipped.
        </Text>

        {/* The template answers what prose cannot: the exact column names, and
            that the sign is the direction. Downloading beats reading. */}
        <div className="lf-import-template">
          <div>
            <Text size="sm" weight="medium">
              Not sure of the format?
            </Text>
            <Text tone="tertiary" size="xs">
              A blank template with the columns filled in, and one example of money out and money in.
            </Text>
          </div>
          <Button variant="secondary" size="sm" onClick={downloadTemplate} loading={downloading}>
            <Download size={15} strokeWidth={1.8} aria-hidden="true" />
            Template
          </Button>
        </div>
        <Select label="Into account" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">Select…</option>
          {accounts?.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
        <Input label="CSV file" type="file" accept=".csv,text/csv" onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
        {importCsv.isPending && (
          <Text tone="tertiary" size="sm">
            Importing…
          </Text>
        )}
        {result && (
          <div className="lf-insight lf-insight--good">
            <p className="lf-insight-title">
              Imported {result.imported} · skipped {result.skipped_duplicate} duplicate
              {result.skipped_duplicate === 1 ? "" : "s"}
            </p>
            {result.errors.length > 0 && (
              <p className="lf-insight-body">
                {result.errors.length} row(s) had problems (e.g. line {result.errors[0].line}: {result.errors[0].error}).
              </p>
            )}
          </div>
        )}
        {error && <Banner tone="danger">{error}</Banner>}
      </Stack>
    </Modal>
  );
}
