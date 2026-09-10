import { useMemo, useState } from "react";
import { ApiError } from "../../api/client";
import type { FinancialAccount } from "../../api/types";
import { useAccountReconciliation, useReconcileTransactions } from "../../hooks/useFinance";
import { formatDate, majorToMinor } from "../../lib/money";
import {
  Banner,
  Button,
  Checkbox,
  Figure,
  FigureRow,
  Input,
  Money,
  Skeleton,
  Text,
  useToast,
} from "../../ui";

/**
 * Tick uncleared rows against a statement until the difference is zero.
 *
 * The API already knows reconciled vs posted and will compute the gap; this
 * panel is the missing surface that lets a person actually *do* the work
 * marketing and the Free tier already promise.
 */
export function ReconcilePanel({ account }: { account: FinancialAccount }) {
  const toast = useToast();
  const [draft, setDraft] = useState("");
  const [statementMinor, setStatementMinor] = useState<number | undefined>();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useAccountReconciliation(account.id, statementMinor);
  const mark = useReconcileTransactions();

  const selectedTotal = useMemo(() => {
    if (!data) return 0;
    return data.uncleared.filter((row) => selected.has(row.id)).reduce((sum, row) => sum + row.amount_minor, 0);
  }, [data, selected]);

  const remaining =
    data?.difference_minor == null ? null : data.difference_minor - selectedTotal;

  const applyStatement = () => {
    setError(null);
    const trimmed = draft.trim();
    if (!trimmed) {
      setStatementMinor(undefined);
      return;
    }
    const parsed = Number(trimmed);
    if (!Number.isFinite(parsed)) {
      setError("Enter the statement balance as a number, e.g. 1250.40");
      return;
    }
    setStatementMinor(majorToMinor(parsed));
    setSelected(new Set());
  };

  const toggle = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const confirm = async () => {
    if (selected.size === 0) return;
    setError(null);
    try {
      const result = await mark.mutateAsync({
        transaction_ids: [...selected],
        reconciled: true,
      });
      toast(`Marked ${result.updated} transaction${result.updated === 1 ? "" : "s"} as cleared`, {
        tone: "success",
      });
      setSelected(new Set());
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't update those transactions.");
    }
  };

  return (
    <div className="lf-recon">
      <div className="lf-section-head">
        <Text tone="secondary" size="sm" style={{ fontWeight: "var(--lf-weight-semibold)" }}>
          Reconcile with a statement
        </Text>
      </div>
      <Text tone="tertiary" size="sm">
        Enter the closing balance from your bank or M-Pesa statement, then tick every
        matching row. The difference is the number you are driving to zero.
      </Text>

      <div className="lf-recon-statement">
        <Input
          label={`Statement balance (${account.currency})`}
          inputMode="decimal"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              applyStatement();
            }
          }}
        />
        <Button variant="secondary" onClick={applyStatement}>
          Check
        </Button>
      </div>

      {isLoading && <Skeleton width="70%" />}

      {data && (
        <>
          <FigureRow>
            <Figure
              label="Ledger"
              amountMinor={data.ledger_balance_minor}
              currency={data.currency}
              neutral
            />
            <Figure
              label="Cleared"
              amountMinor={data.reconciled_minor}
              currency={data.currency}
              neutral
            />
            <Figure
              label={data.difference_minor == null ? "Uncleared" : data.is_balanced ? "Difference" : "Off by"}
              amountMinor={data.difference_minor ?? data.uncleared_minor}
              currency={data.currency}
              tone={
                data.is_balanced
                  ? "positive"
                  : data.difference_minor == null
                    ? "default"
                    : "critical"
              }
            />
          </FigureRow>

          {data.is_balanced && (
            <Banner tone="success">This account matches the statement.</Banner>
          )}
          {data.difference_minor != null && !data.is_balanced && remaining != null && (
            <Text size="sm" tone="secondary">
              {selected.size === 0
                ? "Tick the items that appear on the statement."
                : remaining === 0
                  ? "Confirming these will bring the difference to zero."
                  : "After confirming, still off by "}
              {selected.size > 0 && remaining !== 0 && (
                <Money amountMinor={remaining} currency={data.currency} />
              )}
            </Text>
          )}

          {data.uncleared.length === 0 ? (
            <Text tone="tertiary" size="sm">
              Nothing left uncleared.
            </Text>
          ) : (
            <ul className="lf-recon-list">
              {data.uncleared.map((row) => (
                <li key={row.id} className="lf-recon-row">
                  <Checkbox
                    checked={selected.has(row.id)}
                    onChange={() => toggle(row.id)}
                    aria-label={`Clear ${row.memo?.trim() || "transaction"} on ${formatDate(row.occurred_at)}`}
                  />
                  <div className="lf-row-main">
                    <div className="lf-row-title">{row.memo?.trim() || row.category || "Transaction"}</div>
                    <div className="lf-row-sub">
                      {formatDate(row.occurred_at)}
                      {row.category ? ` · ${row.category}` : ""}
                    </div>
                  </div>
                  <Money amountMinor={row.amount_minor} currency={row.currency} />
                </li>
              ))}
            </ul>
          )}

          {selected.size > 0 && (
            <Button variant="primary" onClick={confirm} loading={mark.isPending}>
              Mark {selected.size} as cleared
            </Button>
          )}
        </>
      )}

      {error && <Banner tone="danger">{error}</Banner>}
    </div>
  );
}
