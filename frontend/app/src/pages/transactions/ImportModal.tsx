import { useState } from "react";
import { ApiError } from "../../api/client";
import { useAccounts, useImportTransactionsCsv } from "../../hooks/useFinance";
import { Banner, Input, Modal, Select, Stack, Text } from "../../ui";

export function ImportModal({ onClose }: { onClose: () => void }) {
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
