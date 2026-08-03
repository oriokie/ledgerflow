import { CheckCircle2 } from "lucide-react";
import { useMemo } from "react";
import { useAccounts, useBills, useCancelBill, usePayBill } from "../hooks/useFinance";
import { Button, Card, EmptyState, PageHeader, SkeletonCard, Text, useToast } from "../ui";
import { BillGroup, BillsSummary, CreateBillForm } from "./bills";
import { billBuckets, billTotals } from "./bills/billsMath";
import { useOpenOnParam } from "../hooks/useOpenOnParam";

/** `embedded` renders this page as a tab panel inside a hub (`/plan`,
 * `/insights`). The hub owns the <h1>, so the page must not render its own
 * PageHeader — two page titles on one route is a broken heading outline. */
export function BillsPage({ embedded }: { embedded?: boolean } = {}) {
  const { data: bills, isLoading } = useBills({ upcoming: 45 });
  const { data: accounts } = useAccounts();
  const payBill = usePayBill();
  const cancelBill = useCancelBill();
  const toast = useToast();
  const [showCreate, setShowCreate] = useOpenOnParam();

  const asOf = useMemo(() => new Date(), []);
  const list = bills ?? [];
  const buckets = billBuckets(list, asOf);
  const totals = billTotals(list, asOf);
  const currency = list[0]?.currency ?? "USD";
  const nothingDue = buckets.overdue.length + buckets.dueThisWeek.length + buckets.later.length === 0;

  const onPay = async (billId: string, accountId: string) => {
    const bill = list.find((b) => b.id === billId);
    await payBill.mutateAsync({ billId, payload: { from_account_id: accountId } });
    toast(bill ? `${bill.name} marked as paid` : "Bill marked as paid");
  };

  const onCancel = async (billId: string) => {
    const bill = list.find((b) => b.id === billId);
    await cancelBill.mutateAsync(billId);
    toast(bill ? `${bill.name} cancelled` : "Bill cancelled", { tone: "info" });
  };

  return (
    <>
      {!embedded && (
        <PageHeader
          eyebrow="Upcoming payments"
          title="Bills"
          actions={
            <Button variant="primary" onClick={() => setShowCreate((v) => !v)}>
              {showCreate ? "Close" : "New bill"}
            </Button>
          }
        />
      )}

      {showCreate && <CreateBillForm onCreated={() => setShowCreate(false)} onCancel={() => setShowCreate(false)} />}

      {isLoading && <SkeletonCard />}

      {!isLoading && list.length === 0 && !showCreate ? (
        <Card>
          <EmptyState
            icon={CheckCircle2}
            title="No upcoming bills"
            body="Add bills like rent and utilities to get a heads-up before they're due and pay them in a click."
            tips={[
              "Recurring bills are created once and repeat on their own schedule.",
              "Due-soon and overdue bills surface on your dashboard automatically.",
              "Marking a bill paid records the transaction for you.",
            ]}
            action={
              <Button variant="primary" onClick={() => setShowCreate(true)}>
                Add a bill
              </Button>
            }
          />
        </Card>
      ) : !isLoading ? (
        <div className="lf-dash-section" style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-2)" }}>
          <BillsSummary totals={totals} currency={currency} />

          {nothingDue ? (
            <Text tone="secondary" style={{ marginTop: "var(--lf-space-3)" }}>
              You're all caught up — nothing due in the next 45 days.
            </Text>
          ) : (
            <>
              <BillGroup title="Overdue" tone="danger" bills={buckets.overdue} accounts={accounts} asOf={asOf} onPay={onPay} onCancel={onCancel} />
              <BillGroup title="Due this week" tone="warning" bills={buckets.dueThisWeek} accounts={accounts} asOf={asOf} onPay={onPay} onCancel={onCancel} />
              <BillGroup title="Later" bills={buckets.later} accounts={accounts} asOf={asOf} onPay={onPay} onCancel={onCancel} />
            </>
          )}
        </div>
      ) : null}
    </>
  );
}
