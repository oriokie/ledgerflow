import { Download, RefreshCw, Upload } from "lucide-react";
import { useState } from "react";
import { financeExtendedApi } from "../api/finance";
import type { RecurringTransaction } from "../api/types";
import { ImportXlsxModal } from "../components/ImportXlsxModal";
import {
  useAccounts,
  useCategories,
  useCancelRecurring,
  useConfirmRecurring,
  useRecurring,
  useSetRecurringActive,
} from "../hooks/useFinance";
import { Button, Card, EmptyState, IconButton, PageHeader, SkeletonCard, useToast } from "../ui";
import { RecurringModal, SubscriptionInsight, SubscriptionRow, SubscriptionSummary } from "./recurring";
import { monthlyMinor } from "./recurring/recurringMath";

/** `embedded` renders this page as a tab panel inside a hub (`/plan`,
 * `/insights`). The hub owns the <h1>, so the page must not render its own
 * PageHeader — two page titles on one route is a broken heading outline. */
export function RecurringPage({ embedded }: { embedded?: boolean } = {}) {
  const { data: recurring, isLoading } = useRecurring();
  const { data: categories } = useCategories();
  const { data: accounts } = useAccounts();
  const setActive = useSetRecurringActive();
  const cancel = useCancelRecurring();
  const confirm = useConfirmRecurring();
  const toast = useToast();
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<RecurringTransaction | null>(null);
  const [showImport, setShowImport] = useState(false);

  const list = recurring ?? [];
  // Biggest cost first — where the easiest savings are.
  const sorted = [...list].sort((a, b) => {
    // active before paused, then by monthly cost desc
    if (a.is_active !== b.is_active) return a.is_active ? -1 : 1;
    return monthlyMinor(b) - monthlyMinor(a);
  });

  const onSetActive = async (recId: string, active: boolean) => {
    await setActive.mutateAsync({ recId, active });
    toast(active ? "Schedule resumed" : "Paused — it won't charge again until you resume it");
  };
  const onCancel = async (recId: string) => {
    await cancel.mutateAsync(recId);
    toast("Cancelled — no further charges from this schedule");
  };
  const onConfirm = async (recId: string, amountMinor: number) => {
    const result = await confirm.mutateAsync({ recId, amount_minor: amountMinor });
    toast(`Recorded — next due ${result.recurring.next_run_on}`);
  };

  return (
    <>
      {!embedded && (
        <PageHeader
          eyebrow="Recurring & subscriptions"
          title="Subscriptions"
          actions={
            <>
              <IconButton
                label="Export CSV"
                icon={<Download size={16} />}
                onClick={() => financeExtendedApi.downloadRecurringCsv()}
              />
              <IconButton label="Import Excel" icon={<Upload size={16} />} onClick={() => setShowImport(true)} />
              <Button variant="primary" onClick={() => setShowCreate(true)}>
                New recurring transaction
              </Button>
            </>
          }
        />
      )}

      {showImport && <ImportXlsxModal target="recurring" onClose={() => setShowImport(false)} />}

      {isLoading && <SkeletonCard />}

      {!isLoading && list.length === 0 ? (
        <Card>
          <EmptyState
            icon={RefreshCw}
            illustration="cycle"
            title="No recurring transactions yet"
            body="Add subscriptions, recurring bills, income, or automatic savings transfers to keep your plan in one place."
            action={
              <Button variant="primary" onClick={() => setShowCreate(true)}>
                Add a recurring transaction
              </Button>
            }
          />
        </Card>
      ) : !isLoading ? (
        <div className="lf-dash-section" style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-4)" }}>
          <SubscriptionSummary recurring={list} />
          <SubscriptionInsight recurring={list} categories={categories} />
          <Card title="All recurring charges">
            {sorted.map((rec) => (
              <SubscriptionRow
                key={rec.id}
                rec={rec}
                categories={categories}
                accounts={accounts}
                onSetActive={onSetActive}
                onCancel={onCancel}
                onConfirm={onConfirm}
                onEdit={setEditing}
              />
            ))}
          </Card>
        </div>
      ) : null}

      <RecurringModal open={showCreate} onClose={() => setShowCreate(false)} />
      <RecurringModal open={!!editing} editing={editing} onClose={() => setEditing(null)} />
    </>
  );
}
