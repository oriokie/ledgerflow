import { ArrowLeftRight, Download, RefreshCw, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { financeApi, financeExtendedApi } from "../api/finance";
import type { Transaction } from "../api/types";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { useApplyAutomationRules } from "../hooks/useIntelligence";
import {
  useAccounts,
  useBulkUpdateTransactions,
  useBulkVoidTransactions,
  useCategories,
  usePayees,
  useTransactions,
  useUpdateTransaction,
} from "../hooks/useFinance";
import { ApiError } from "../api/client";
import { Banner, Button, Card, EmptyState, IconButton, Inline, PageHeader, Skeleton, Stack, Text, useToast } from "../ui";
import {
  AddTransactionForm,
  BulkActionBar,
  FilterBar,
  ImportModal,
  TransactionDetail,
  TransactionTable,
} from "./transactions";
import { bulkMessage } from "./transactions/bulk";
import { countActiveFilters, filtersToParams, parseCursor, parseFilters, toApiFilters } from "./transactions/filters";

/** `embedded` renders this page as a tab panel inside a hub (`/plan`,
 * `/insights`). The hub owns the <h1>, so the page must not render its own
 * PageHeader — two page titles on one route is a broken heading outline. */
export function TransactionsPage({ embedded }: { embedded?: boolean } = {}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useMemo(() => parseFilters(searchParams), [searchParams]);

  const [searchInput, setSearchInput] = useState(filters.q);
  const debouncedSearch = useDebouncedValue(searchInput, 300);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showAdd, setShowAdd] = useState(() => searchParams.get("add") === "1");
  const [showImport, setShowImport] = useState(() => searchParams.get("import") === "1");
  const [detailTxn, setDetailTxn] = useState<Transaction | null>(null);
  const [bulkNote, setBulkNote] = useState<{ tone: "success" | "warning" | "danger"; text: string } | null>(null);

  const { data: accounts } = useAccounts();
  const { data: categories } = useCategories();
  const { data: payees } = usePayees();
  const updateTxn = useUpdateTransaction();
  const toast = useToast();
  const bulkUpdate = useBulkUpdateTransactions();
  const bulkVoid = useBulkVoidTransactions();
  const applyRules = useApplyAutomationRules();

  // Apply a new filter state: reset paging + selection so results stay coherent.
  const applyFilters = useCallback(
    (next: typeof filters) => {
      setSearchParams(filtersToParams(next), { replace: true });
      setCursor(null);
      setSelected(new Set());
    },
    [setSearchParams],
  );

  // Push debounced search into the URL (no history spam, no refetch per keystroke).
  useEffect(() => {
    if (debouncedSearch !== filters.q) applyFilters({ ...filters, q: debouncedSearch });
  }, [debouncedSearch, filters, applyFilters]);

  const apiFilters = useMemo(() => toApiFilters(filters, cursor ?? undefined), [filters, cursor]);
  const { data: page, isLoading } = useTransactions(apiFilters);
  const rows = page?.results ?? [];
  const txId = searchParams.get("tx");

  useEffect(() => {
    if (!txId) return;
    let cancelled = false;
    financeApi
      .getTransaction(txId)
      .then((txn) => {
        if (!cancelled) setDetailTxn(txn);
      })
      .catch(() => {
        /* missing or unauthorized: leave the list as-is */
      });
    return () => {
      cancelled = true;
    };
  }, [txId]);

  // Selection helpers
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleAll = () =>
    setSelected((prev) => {
      const allSelected = rows.length > 0 && rows.every((r) => prev.has(r.id));
      if (allSelected) return new Set();
      return new Set(rows.map((r) => r.id));
    });
  const clearSelection = () => setSelected(new Set());

  const goToPage = (next: string | null) => {
    setCursor(next);
    clearSelection();
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // Bulk actions
  const bulkCategorize = async (categoryId: string) => {
    const ids = [...selected];
    const res = await bulkUpdate.mutateAsync({ ids, payload: { category_id: categoryId } });
    setBulkNote(bulkMessage(res, "Categorized"));
    clearSelection();
  };
  const bulkVoidSelected = async () => {
    // A transfer (and a split) is several rows on one journal. Sending every
    // selected id used to reverse that journal once per row and overshoot
    // the accounts. One id per movement is enough — the server voids siblings.
    const chosen = rows.filter((r) => selected.has(r.id));
    const seen = new Set<string>();
    const ids: string[] = [];
    for (const row of chosen) {
      const group = row.transfer_group ?? row.split_group ?? row.id;
      if (seen.has(group)) continue;
      seen.add(group);
      ids.push(row.id);
    }
    const res = await bulkVoid.mutateAsync({ ids });
    setBulkNote(bulkMessage(res, "Voided"));
    clearSelection();
  };

  const applyRulesNow = async () => {
    try {
      const result = await applyRules.mutateAsync({ scope: "uncategorized" });
      toast(`Applied rules to ${result.matched} of ${result.scanned} uncategorized transaction${result.scanned === 1 ? "" : "s"}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.detail : "Couldn't apply rules.");
    }
  };

  const inlineCategorize = (txnId: string, categoryId: string | null) => {
    // The cache updates instantly (see useUpdateTransaction), so the only thing
    // left to handle here is failure: without this, a rejected save would roll
    // the category back on screen with no explanation, and the user would think
    // the app simply ignored them.
    updateTxn.mutate(
      { txnId, payload: { category_id: categoryId } },
      {
        onError: (err) =>
          toast(err instanceof ApiError ? err.detail : "Couldn't save that category — it's been put back."),
      },
    );
  };

  const hasFilters = countActiveFilters(filters) > 0 || !!filters.q;

  return (
    <>
      {!embedded && (
        <PageHeader
          eyebrow="Position"
          title="Activity"
          description="Every movement through your accounts — search, filter, and keep the ledger honest."
          illustration="path"
          actions={
            <>
              <IconButton
                label="Apply automation rules to uncategorized transactions"
                icon={<RefreshCw size={16} />}
                onClick={applyRulesNow}
                disabled={applyRules.isPending}
              />
              <IconButton label="Export CSV" icon={<Download size={16} />} onClick={() => financeExtendedApi.downloadExport(apiFilters)} />
              <IconButton label="Import CSV" icon={<Upload size={16} />} onClick={() => setShowImport(true)} />
              <Button variant="primary" onClick={() => setShowAdd((v) => !v)}>
                {showAdd ? "Close" : "Add transaction"}
              </Button>
            </>
          }
        />
      )}

      {showAdd && <AddTransactionForm onClose={() => setShowAdd(false)} />}

      <FilterBar
        state={filters}
        onChange={applyFilters}
        searchValue={searchInput}
        onSearchChange={setSearchInput}
        accounts={accounts}
        categories={categories}
      />

      {selected.size > 0 && (
        <BulkActionBar
          count={selected.size}
          categories={categories}
          onCategorize={bulkCategorize}
          onVoid={bulkVoidSelected}
          onClear={clearSelection}
          pending={bulkUpdate.isPending || bulkVoid.isPending}
        />
      )}

      {bulkNote && (
        <div style={{ marginBottom: "var(--lf-space-3)" }}>
          <Banner tone={bulkNote.tone} onDismiss={() => setBulkNote(null)}>
            {bulkNote.text}
          </Banner>
        </div>
      )}

      {isLoading && (
        <Stack gap={2}>
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} width={`${70 - i * 10}%`} />
          ))}
        </Stack>
      )}

      {!isLoading && rows.length === 0 && (
        <Card>
          {hasFilters ? (
            <EmptyState
              icon={ArrowLeftRight}
              illustration="no-results"
              title="No matching transactions"
              body="No transactions match the current search and filters."
              action={
                <Button variant="secondary" onClick={() => applyFilters(parseFilters(new URLSearchParams()))}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={ArrowLeftRight}
              illustration="no-data"
              title="No transactions yet"
              body="Record your first expense or income — or import a CSV from your bank to backfill history."
              tips={[
                "Importing a CSV backfills months of history in one pass.",
                "Categories are suggested automatically as you record more.",
                "Every amount is stored in its original currency, converted only for reports.",
              ]}
              action={
                <Inline gap={2}>
                  <Button variant="primary" onClick={() => setShowAdd(true)}>
                    Add transaction
                  </Button>
                  <Button variant="secondary" onClick={() => setShowImport(true)}>
                    Import CSV
                  </Button>
                </Inline>
              }
            />
          )}
        </Card>
      )}

      {!isLoading && rows.length > 0 && (
        <>
          <TransactionTable
            rows={rows}
            accounts={accounts}
            categories={categories}
            payees={payees}
            selected={selected}
            onToggle={toggle}
            onToggleAll={toggleAll}
            onOpen={setDetailTxn}
            onCategorize={inlineCategorize}
          />

          {(page?.previous || page?.next) && (
            <Inline gap={2} style={{ marginTop: "var(--lf-space-4)", justifyContent: "flex-end" }}>
              <Button
                variant="secondary"
                disabled={!page?.previous}
                onClick={() => goToPage(parseCursor(page?.previous ?? null))}
              >
                Previous
              </Button>
              <Button variant="secondary" disabled={!page?.next} onClick={() => goToPage(parseCursor(page?.next ?? null))}>
                Next
              </Button>
            </Inline>
          )}

          <Text tone="tertiary" size="sm" style={{ marginTop: "var(--lf-space-2)" }}>
            Showing {rows.length} transaction{rows.length === 1 ? "" : "s"}
            {selected.size > 0 ? ` · ${selected.size} selected` : ""}
          </Text>
        </>
      )}

      {detailTxn && (
        <TransactionDetail
          txn={detailTxn}
          onClose={() => {
            setDetailTxn(null);
            if (searchParams.get("tx")) {
              const next = new URLSearchParams(searchParams);
              next.delete("tx");
              setSearchParams(next, { replace: true });
            }
          }}
        />
      )}
      {showImport && <ImportModal onClose={() => setShowImport(false)} />}
    </>
  );
}
