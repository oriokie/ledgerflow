import { RefreshCw } from "lucide-react";
import { useState } from "react";
import type { RecurringTransaction } from "../api/types";
import { useCategories, useCancelRecurring, useRecurring, useSetRecurringActive } from "../hooks/useFinance";
import { Button, Card, EmptyState, PageHeader, SkeletonCard, useToast } from "../ui";
import { RecurringModal, SubscriptionInsight, SubscriptionRow, SubscriptionSummary } from "./recurring";
import { monthlyMinor } from "./recurring/recurringMath";

/** `embedded` renders this page as a tab panel inside a hub (`/plan`,
 * `/insights`). The hub owns the <h1>, so the page must not render its own
 * PageHeader — two page titles on one route is a broken heading outline. */
export function RecurringPage({ embedded }: { embedded?: boolean } = {}) {
  const { data: recurring, isLoading } = useRecurring();
  const { data: categories } = useCategories();
  const setActive = useSetRecurringActive();
  const cancel = useCancelRecurring();
  const toast = useToast();
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<RecurringTransaction | null>(null);

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

  return (
    <>
      {!embedded && (
        <PageHeader
          eyebrow="Recurring & subscriptions"
          title="Subscriptions"
          actions={
            <Button variant="primary" onClick={() => setShowCreate(true)}>
              New recurring charge
            </Button>
          }
        />
      )}

      {isLoading && <SkeletonCard />}

      {!isLoading && list.length === 0 ? (
        <Card>
          <EmptyState
            icon={RefreshCw}
            title="No recurring charges yet"
            body="Add your subscriptions and recurring bills — streaming, gym, rent — to see what they cost each month and spot what to trim."
            action={
              <Button variant="primary" onClick={() => setShowCreate(true)}>
                Add a recurring charge
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
                onSetActive={onSetActive}
                onCancel={onCancel}
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
