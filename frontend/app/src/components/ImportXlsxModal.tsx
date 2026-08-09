import { Download } from "lucide-react";
import { useState } from "react";
import { ApiError } from "../api/client";
import { financeExtendedApi } from "../api/finance";
import { useImportBillsXlsx, useImportRecurringXlsx } from "../hooks/useFinance";
import { Banner, Button, Input, Modal, Stack, Text } from "../ui";

type ImportTarget = "bills" | "recurring";

/** Not the transaction/statement importer (that stays CSV-only) — this is for
 * a human filling in a spreadsheet by hand to enter many bills or recurring
 * charges at once. One shared modal for both targets: they differ only in
 * endpoint and labels, which a `target` prop absorbs cleanly. */
const COPY: Record<ImportTarget, { title: string; hint: string; filename: string }> = {
  bills: {
    title: "Import bills",
    hint: "Needs name, amount, currency, and due date columns. Payee, category, and recurrence are optional, matched by name.",
    filename: "ledgerflow-bills-template.xlsx",
  },
  recurring: {
    title: "Import recurring charges",
    hint: "Needs type, account, amount, currency, frequency, and start date columns. Category, payee, and counter account are optional, matched by name.",
    filename: "ledgerflow-recurring-template.xlsx",
  },
};

export function ImportXlsxModal({ target, onClose }: { target: ImportTarget; onClose: () => void }) {
  const [downloading, setDownloading] = useState(false);
  const [result, setResult] = useState<{ created: number; errors: { row: number; message: string }[] } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);

  const importBills = useImportBillsXlsx();
  const importRecurring = useImportRecurringXlsx();
  const mutation = target === "bills" ? importBills : importRecurring;
  const copy = COPY[target];

  /* Fetched rather than linked, because the endpoint is tenant-scoped and
     needs the auth header a bare <a href> cannot carry. */
  const downloadTemplate = async () => {
    setDownloading(true);
    try {
      const blob = await (target === "bills"
        ? financeExtendedApi.billsImportTemplate()
        : financeExtendedApi.recurringImportTemplate());
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = copy.filename;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(false);
    }
  };

  const onFile = async (file: File) => {
    setError(null);
    setResult(null);
    try {
      setResult(await mutation.mutateAsync(file));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Import failed.");
    }
  };

  return (
    <Modal open onClose={onClose} title={copy.title}>
      <Stack gap={4}>
        <Text tone="tertiary" size="sm">
          {copy.hint}
        </Text>

        <div className="lf-import-template">
          <div>
            <Text size="sm" weight="medium">
              Not sure of the format?
            </Text>
            <Text tone="tertiary" size="xs">
              A blank spreadsheet with the columns filled in and one example row.
            </Text>
          </div>
          <Button variant="secondary" size="sm" onClick={downloadTemplate} loading={downloading}>
            <Download size={15} strokeWidth={1.8} aria-hidden="true" />
            Template
          </Button>
        </div>

        <Input
          label="Excel file"
          type="file"
          accept=".xlsx"
          onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
        />
        {mutation.isPending && (
          <Text tone="tertiary" size="sm">
            Importing…
          </Text>
        )}
        {result && (
          <div className="lf-insight lf-insight--good">
            <p className="lf-insight-title">Created {result.created}</p>
            {result.errors.length > 0 && (
              <p className="lf-insight-body">
                {result.errors.length} row(s) had problems (e.g. row {result.errors[0].row}:{" "}
                {result.errors[0].message}).
              </p>
            )}
          </div>
        )}
        {error && <Banner tone="danger">{error}</Banner>}
      </Stack>
    </Modal>
  );
}
