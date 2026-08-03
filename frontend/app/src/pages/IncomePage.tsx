import { Banknote } from "lucide-react";
import { useDeleteIncomeSource, useIncomeSources, useIncomeSummary } from "../hooks/useIncome";
import { useOpenOnParam } from "../hooks/useOpenOnParam";
import { Button, Card, EmptyState, Grid, PageHeader, Skeleton, Stack } from "../ui";
import {
  CommittedIncomeCard,
  CreateIncomeSourceForm,
  IncomeSourceCard,
  IncomeSummaryCards,
} from "./income";

/**
 * The income screen.
 *
 * The product modelled every way money leaves and had no model of how it
 * arrives. This is the other half of the balance sheet: what you are paid, what
 * is withheld from it, how steady it is, and how much of it is already spoken
 * for before you choose anything.
 *
 * Order is deliberate. The committed-income figure sits above the list of
 * sources because it is the answer; the sources are the working. A screen that
 * leads with a list of arrangements makes the user do the arithmetic the
 * product exists to do for them.
 */
export function IncomePage() {
  const { data: sources, isLoading } = useIncomeSources();
  const { data: summary } = useIncomeSummary();
  const deleteSource = useDeleteIncomeSource();
  const [showCreate, setShowCreate] = useOpenOnParam();

  const hasSources = (sources?.length ?? 0) > 0;

  return (
    <>
      <PageHeader
        eyebrow="Money in"
        title="Income"
        actions={
          <Button variant="primary" onClick={() => setShowCreate((v) => !v)}>
            {showCreate ? "Close" : "Add income"}
          </Button>
        }
      />

      {showCreate && (
        <CreateIncomeSourceForm
          onCreated={() => setShowCreate(false)}
          onCancel={() => setShowCreate(false)}
        />
      )}

      {isLoading && <Skeleton width="50%" />}

      {sources && !hasSources && !showCreate && (
        <Card>
          <EmptyState
            icon={Banknote}
            title="Tell us what you earn"
            body="LedgerFlow knows what leaves your account. Adding what comes in is what lets it say how much of your money is actually yours to direct."
            tips={[
              "Enter what lands in your account — the gross is optional.",
              "Mark income that varies, and it will be projected from what you're actually paid rather than a number you typed once.",
              "Record deductions to see your real take-home rate.",
            ]}
            action={
              <Button variant="primary" onClick={() => setShowCreate(true)}>
                Add income
              </Button>
            }
          />
        </Card>
      )}

      {summary && (
        <Stack gap={4}>
          <IncomeSummaryCards summary={summary} />
          <CommittedIncomeCard summary={summary} />
        </Stack>
      )}

      {hasSources && (
        <Grid cols={2} gap={4}>
          {sources!.map((source) => (
            <IncomeSourceCard
              key={source.id}
              source={source}
              onDelete={(id) => deleteSource.mutate(id)}
            />
          ))}
        </Grid>
      )}
    </>
  );
}
