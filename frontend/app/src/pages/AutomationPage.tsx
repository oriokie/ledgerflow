import { RefreshCw, Sparkles } from "lucide-react";
import { useState } from "react";
import { useAutomationQueue, useBulkDecide, useDecideSuggestion, useScan } from "../hooks/useAutomation";
import { Button, Card, EmptyState, Inline, PageHeader, SkeletonCard, Text } from "../ui";
import { SuggestionCard } from "./automation";

/**
 * The review queue.
 *
 * The governing rule of the whole feature is visible here: everything is a
 * proposal awaiting a decision. Nothing in this list has already happened
 * except high-confidence categorisations, which are marked as applied and
 * remain reversible.
 *
 * Bulk selection exists because a backlog reviewed one tap at a time is a
 * backlog nobody finishes.
 */
export function AutomationPage() {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const { data: queue, isLoading } = useAutomationQueue();
  const scan = useScan();
  const decide = useDecideSuggestion();
  const bulk = useBulkDecide();

  const suggestions = queue?.suggestions ?? [];

  const toggle = (id: string) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const decideAll = (decision: "approve" | "reject") => {
    bulk.mutate({ ids: [...selected], decision });
    setSelected(new Set());
  };

  return (
    <>
      <PageHeader
        title="Review"
        eyebrow={queue ? `${queue.pending} waiting` : undefined}
        description="Things LedgerFlow noticed. Nothing here has been applied unless it says so."
        actions={
          <Button
            variant="secondary"
            loading={scan.isPending}
            onClick={() => scan.mutate(undefined)}
            icon={<RefreshCw size={15} aria-hidden="true" />}
          >
            Scan again
          </Button>
        }
      />

      {isLoading && <SkeletonCard />}

      {!isLoading && suggestions.length === 0 && (
        <Card>
          <EmptyState
            icon={Sparkles}
            title="Nothing to review"
            body="Your transactions look tidy. New suggestions appear as transactions come in."
            tips={[
              "Transfers between your own accounts are matched so they don't count as income or spending.",
              "Categories are suggested from how you've categorised the same merchant before.",
              "Dismissing a suggestion teaches the engine — it won't ask again.",
            ]}
          />
        </Card>
      )}

      {suggestions.length > 0 && (
        <>
          {/* Bulk bar appears only with a selection — an always-present toolbar
              of disabled buttons is just clutter. */}
          {selected.size > 0 && (
            <div className="lf-suggestion-bulk" role="status">
              <Text as="span" size="sm">
                {selected.size} selected
              </Text>
              <Inline gap={2}>
                <Button variant="secondary" size="sm" onClick={() => decideAll("reject")}>
                  Dismiss all
                </Button>
                <Button variant="primary" size="sm" onClick={() => decideAll("approve")}>
                  Accept all
                </Button>
              </Inline>
            </div>
          )}

          <div className="lf-suggestion-list">
            {suggestions.map((suggestion) => (
              <SuggestionCard
                key={suggestion.id}
                suggestion={suggestion}
                selected={selected.has(suggestion.id)}
                onSelect={toggle}
                onDecide={(id, decision) => decide.mutate({ id, decision })}
              />
            ))}
          </div>

          {queue?.approval_rate !== null && queue?.approval_rate !== undefined && (
            <Text tone="tertiary" size="xs">
              You've accepted {Math.round(queue.approval_rate * 100)}% of suggestions so far.
            </Text>
          )}
        </>
      )}
    </>
  );
}
