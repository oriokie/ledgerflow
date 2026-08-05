import { HandCoins } from "lucide-react";
import { useReceivables, useReceivableSummary } from "../hooks/useReceivables";
import { useOpenOnParam } from "../hooks/useOpenOnParam";
import { Button, Card, EmptyState, Grid, Figure, PageHeader, Skeleton, Text } from "../ui";
import { CreateReceivableForm, ReceivableRow } from "./receivables";

/**
 * The receivables screen — money other people owe you.
 *
 * The product modelled every liability in detail and had no model of the other
 * direction at all: a household could record that it owed a friend, but not
 * that a friend owed it. For the informal lending most households actually do,
 * that money is often the largest single thing they are owed and the one most
 * likely to be forgotten.
 *
 * Order follows the same rule as the income screen: the headline figure sits
 * above the list because it is the answer, and the list is the working.
 */
export function ReceivablesPage() {
  const { data: rows, isLoading } = useReceivables();
  const { data: summary } = useReceivableSummary();
  const [showCreate, setShowCreate] = useOpenOnParam();

  const hasRows = (rows?.length ?? 0) > 0;
  const outstanding = (rows ?? []).filter((r) => r.status === "outstanding");
  const closed = (rows ?? []).filter((r) => r.status !== "outstanding");

  return (
    <>
      <PageHeader
        eyebrow="Owed to you"
        title="Receivables"
        description="Money you're waiting to get back, and how long you've been waiting."
        actions={
          <Button variant="primary" onClick={() => setShowCreate((v) => !v)}>
            {showCreate ? "Close" : "Add what you're owed"}
          </Button>
        }
      />

      {showCreate && (
        <CreateReceivableForm
          onCreated={() => setShowCreate(false)}
          onCancel={() => setShowCreate(false)}
        />
      )}

      {isLoading && <Skeleton width="50%" />}

      {rows && !hasRows && !showCreate && (
        <Card>
          <EmptyState
            icon={HandCoins}
            title="Nothing owed to you"
            body="LedgerFlow tracks what you owe in detail. This is the other direction — the money you've lent out, invoiced, or fronted for someone and haven't got back yet."
            tips={[
              "A name and an amount is enough. A repayment date is optional, because most lending between people doesn't have one.",
              "Record part-payments as they come in — the outstanding figure follows them.",
              "Writing something off keeps the record rather than erasing it.",
            ]}
            action={
              <Button variant="primary" onClick={() => setShowCreate(true)}>
                Add what you're owed
              </Button>
            }
          />
        </Card>
      )}

      {summary && (
        <Grid cols={3} gap={4}>
          <Card>
            <Figure
              label="Still owed to you"
              amountMinor={summary.outstanding_minor}
              currency={summary.currency}
              size="hero"
            />
            <Text tone="tertiary" size="xs">
              across {summary.count} {summary.count === 1 ? "person" : "people"}
            </Text>
          </Card>
          <Card>
            <Figure
              label="Overdue"
              amountMinor={summary.overdue_minor}
              currency={summary.currency}
            />
            <Text tone="tertiary" size="xs">
              {summary.overdue_count === 0
                ? "Nothing past an agreed date"
                : `${summary.overdue_count} past the date agreed`}
            </Text>
          </Card>
          <Card>
            <Figure
              label="Written off"
              amountMinor={summary.written_off_minor}
              currency={summary.currency}
            />
            <Text tone="tertiary" size="xs">
              Kept on the record, not counted
            </Text>
          </Card>
        </Grid>
      )}

      {outstanding.length > 0 && (
        <Card title="Outstanding">
          {outstanding.map((row) => (
            <ReceivableRow key={row.id} row={row} />
          ))}
        </Card>
      )}

      {closed.length > 0 && (
        <Card title="Settled and written off">
          {closed.map((row) => (
            <ReceivableRow key={row.id} row={row} />
          ))}
        </Card>
      )}
    </>
  );
}
