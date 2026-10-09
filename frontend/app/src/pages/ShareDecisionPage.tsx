import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { advisorApi, type DecisionResult } from "../api/projections";
import { downloadFile } from "../lib/download";
import { Banner, Button, Inline, Stack, Text, ToastProvider, useToast } from "../ui";
import { LegalShell } from "./LegalPage";
import { Answer } from "./projections/DecisionAssistant";

export function ShareDecisionPage() {
  return (
    <ToastProvider>
      <ShareDecisionBody />
    </ToastProvider>
  );
}

function ShareDecisionBody() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const toast = useToast();
  const [result, setResult] = useState<DecisionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"pdf" | "xlsx" | null>(null);

  useEffect(() => {
    if (!token) {
      setError("This share link is missing or malformed.");
      return;
    }
    advisorApi
      .shared(token)
      .then(setResult)
      .catch((err) => {
        setError(
          err instanceof ApiError ? err.detail : "This share link is invalid or has expired.",
        );
      });
  }, [token]);

  const download = async (kind: "pdf" | "xlsx") => {
    setBusy(kind);
    try {
      await downloadFile(
        `/projections/shared/${encodeURIComponent(token)}/export.${kind}`,
        `ledgerflow-decision.${kind}`,
      );
    } catch (err) {
      toast(err instanceof ApiError ? err.detail : "Couldn't download that file.", { tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <LegalShell title={result?.question ?? "Shared decision"}>
      {error && <Banner tone="danger">{error}</Banner>}
      {!error && !result && <Text tone="secondary">Loading this result…</Text>}
      {result && (
        <Stack gap={4}>
          <Answer result={result} />
          <Inline gap={2} wrap>
            <Button variant="secondary" loading={busy === "pdf"} onClick={() => download("pdf")}>
              Download PDF
            </Button>
            <Button variant="secondary" loading={busy === "xlsx"} onClick={() => download("xlsx")}>
              Download Excel
            </Button>
          </Inline>
        </Stack>
      )}
    </LegalShell>
  );
}
