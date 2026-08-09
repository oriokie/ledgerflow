import { PieChart, Trash2 } from "lucide-react";
import { useState } from "react";
import { useCategories } from "../hooks/useFinance";
import {
  useBudgets,
  useBudgetStatus,
  useDeleteBudget,
  useRemoveBudgetLine,
  useUpdateBudgetLine,
} from "../hooks/useBudgeting";
import { Button, Card, EmptyState, Inline, PageHeader, SkeletonCard, Tabs, Text, useToast } from "../ui";
import {
  AddLineForm,
  BudgetAlerts,
  BudgetLineRow,
  BudgetSummary,
  CreateBudgetForm,
  SmartBudgetPanel,
} from "./budgets";
import { budgetAlerts, paceIsMeaningful, periodProgress, sortLinesByRisk } from "./budgets/budgetMath";
import { useOpenOnParam } from "../hooks/useOpenOnParam";

/** `embedded` renders this page as a tab panel inside a hub (`/plan`,
 * `/insights`). The hub owns the <h1>, so the page must not render its own
 * PageHeader — two page titles on one route is a broken heading outline. */
export function BudgetsPage({ embedded }: { embedded?: boolean } = {}) {
  const { data: budgets, isLoading } = useBudgets();
  const { data: categories } = useCategories();
  const [selectedBudgetId, setSelectedBudgetId] = useState<string | undefined>(undefined);
  const [showCreate, setShowCreate] = useOpenOnParam();
  const [showSuggest, setShowSuggest] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const toast = useToast();

  const activeBudgetId = selectedBudgetId ?? budgets?.[0]?.id;
  const activeBudget = budgets?.find((b) => b.id === activeBudgetId);
  const { data: status } = useBudgetStatus(activeBudgetId);

  const updateLine = useUpdateBudgetLine();
  const removeLine = useRemoveBudgetLine();
  const deleteBudget = useDeleteBudget();

  const currency = activeBudget?.currency ?? "USD";
  const lines = status?.lines ?? [];
  const sortedLines = sortLinesByRisk(lines);
  const pace = status ? periodProgress(status) : null;
  const pacePercent = pace?.elapsedPercent ?? 0;
  // Shared with the summary so the page cannot say "too early to tell" at the
  // top while every category below it claims to be on track.
  const paceJudgeable = pace ? paceIsMeaningful(pace) : false;

  const expenseCategories = categories?.filter((c) => c.kind === "expense") ?? [];
  const budgetedCategoryIds = new Set(lines.map((l) => l.category_id));
  const availableCategories = expenseCategories.filter((c) => !budgetedCategoryIds.has(c.id));

  const { over, warning } = budgetAlerts(lines);
  const allClear = lines.length > 0 && over.length === 0 && warning.length === 0;

  const onUpdateLimit = (lineId: string, limitMinor: number) =>
    updateLine.mutateAsync({ budgetId: activeBudgetId!, lineId, payload: { limit_minor: limitMinor } });
  const onRemove = (lineId: string) => removeLine.mutateAsync({ budgetId: activeBudgetId!, lineId });

  const doDeleteBudget = async () => {
    if (!activeBudgetId) return;
    const name = activeBudget?.name ?? "Budget";
    await deleteBudget.mutateAsync(activeBudgetId);
    setSelectedBudgetId(undefined);
    setConfirmDelete(false);
    toast(`${name} deleted`, { tone: "info" });
  };

  return (
    <>
      {!embedded && (
        <PageHeader
          eyebrow={activeBudget?.period ?? "\u00a0"}
          title="Budgets"
          actions={
            <Inline gap={2}>
              <Button variant="secondary" onClick={() => setShowSuggest((v) => !v)}>
                {showSuggest ? "Close suggestion" : "Suggest a budget"}
              </Button>
              <Button variant="primary" onClick={() => setShowCreate((v) => !v)}>
                {showCreate ? "Close" : "New budget"}
              </Button>
            </Inline>
          }
        />
      )}

      {showSuggest && (
        <SmartBudgetPanel
          onCreated={(id) => {
            setSelectedBudgetId(id);
            setShowSuggest(false);
          }}
          onCancel={() => setShowSuggest(false)}
        />
      )}

      {showCreate && (
        <CreateBudgetForm
          onCreated={(id) => {
            setSelectedBudgetId(id);
            setShowCreate(false);
          }}
          onCancel={() => setShowCreate(false)}
        />
      )}

      {isLoading && <SkeletonCard />}

      {budgets && budgets.length === 0 && !showCreate && (
        <Card>
          <EmptyState
            icon={PieChart}
            title="No budgets yet"
            body="Create a budget to set category limits and track spending against them through the month."
            tips={[
              "Set a limit per category — groceries, transport, eating out.",
              "Progress bars turn amber as you approach a limit, red once past it.",
              "Budgets roll forward each period, so you set them up once.",
            ]}
            action={
              <Inline gap={2}>
                <Button variant="primary" onClick={() => setShowSuggest(true)}>
                  Suggest one from my history
                </Button>
                <Button variant="secondary" onClick={() => setShowCreate(true)}>
                  Start from scratch
                </Button>
              </Inline>
            }
          />
        </Card>
      )}

      {budgets && budgets.length > 1 && activeBudgetId && (
        <Tabs
          label="Select budget"
          value={activeBudgetId}
          onChange={(v) => {
            setSelectedBudgetId(v);
            setConfirmDelete(false);
          }}
          tabs={budgets.map((b) => ({ value: b.id, label: b.name }))}
        />
      )}

      {activeBudgetId && status && (
        <div className="lf-dash-section" style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-4)" }}>
          {lines.length > 0 && <BudgetSummary status={status} currency={currency} />}

          <BudgetAlerts lines={lines} currency={currency} />

          {/* Good news does not need a panel. This was a full bordered card
              with a heading and a body paragraph to say that nothing has
              happened — giving the absence of problems more weight on the page
              than most of the problems would have got. One line, stated once. */}
          {allClear && (
            // `role="status"` lives on the wrapper because the all-clear
            // appears and disappears as spending moves, and a screen reader
            // should hear it change without the line being announced twice.
            <div role="status">
              <Text tone="tertiary" size="sm">
                Nothing over or nearing its limit this period.
              </Text>
            </div>
          )}

          {lines.length > 0 ? (
            <Card title="Categories">
              {sortedLines.map((line) => (
                <BudgetLineRow
                  key={line.line_id}
                  line={line}
                  currency={currency}
                  pacePercent={pacePercent}
                  paceJudgeable={paceJudgeable}
                  onUpdateLimit={onUpdateLimit}
                  onRemove={onRemove}
                />
              ))}
            </Card>
          ) : (
            <Text tone="secondary">Add a category below to start tracking this budget.</Text>
          )}

          {activeBudgetId && <AddLineForm budgetId={activeBudgetId} availableCategories={availableCategories} />}

          <div>
            {confirmDelete ? (
              <Inline gap={2}>
                <Text tone="secondary" size="sm">
                  Delete this budget?
                </Text>
                <Button variant="danger" size="sm" loading={deleteBudget.isPending} onClick={doDeleteBudget}>
                  Delete budget
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
                  Cancel
                </Button>
              </Inline>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                icon={<Trash2 size={15} strokeWidth={1.8} />}
                onClick={() => setConfirmDelete(true)}
              >
                Delete budget
              </Button>
            )}
          </div>
        </div>
      )}
    </>
  );
}
