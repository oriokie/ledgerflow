import {
  ArrowLeftRight,
  Copy,
  Repeat,
  RotateCcw,
  Split,
  Tag,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import type { AutomationKind, AutomationSuggestion } from "../../api/types";
import { Button, Checkbox, Text } from "../../ui";

const ICONS: Record<AutomationKind, LucideIcon> = {
  category: Tag,
  transfer: ArrowLeftRight,
  duplicate: Copy,
  refund: RotateCcw,
  recurring: Repeat,
  split: Split,
  income: TrendingUp,
};

const LABELS: Record<AutomationKind, string> = {
  category: "Category",
  transfer: "Transfer",
  duplicate: "Possible duplicate",
  refund: "Refund",
  recurring: "Recurring charge",
  split: "Worth splitting",
  income: "Income",
};

/**
 * Confidence, in words.
 *
 * Banded rather than shown as "62%". A detector's confidence is a calibrated
 * estimate, and rendering it to the point implies a precision it doesn't have —
 * the same reasoning as the goal forecast. The exact value stays in the API for
 * anyone who wants it.
 */
function confidenceLabel(confidence: number): string {
  if (confidence >= 0.85) return "Very likely";
  if (confidence >= 0.65) return "Likely";
  return "Worth checking";
}

/**
 * One proposal awaiting a decision.
 *
 * The reason is shown always, not behind a disclosure — unlike a coach insight
 * this asks the user to *act*, and nobody should approve something without
 * seeing why it was proposed.
 */
export function SuggestionCard({
  suggestion,
  selected,
  onSelect,
  onDecide,
}: {
  suggestion: AutomationSuggestion;
  selected: boolean;
  onSelect: (id: string) => void;
  onDecide: (id: string, decision: "approve" | "reject") => void;
}) {
  const Icon = ICONS[suggestion.kind] ?? Tag;

  return (
    <article className="lf-suggestion" data-kind={suggestion.kind}>
      <Checkbox
        label=""
        aria-label={`Select ${LABELS[suggestion.kind]} suggestion`}
        checked={selected}
        onChange={() => onSelect(suggestion.id)}
      />

      <span className="lf-suggestion-icon" aria-hidden="true">
        <Icon size={15} strokeWidth={1.9} />
      </span>

      <div className="lf-suggestion-body">
        <p className="lf-suggestion-kind">
          {LABELS[suggestion.kind]}
          <span className="lf-suggestion-confidence">
            {confidenceLabel(suggestion.confidence)}
          </span>
        </p>
        {/* Always visible: this asks the user to act, so the reasoning can't
            sit behind a disclosure. */}
        <p className="lf-suggestion-reason">{suggestion.reason}</p>
        {suggestion.transaction_ids.length > 1 && (
          <Text as="span" tone="tertiary" size="xs">
            {suggestion.transaction_ids.length} transactions
          </Text>
        )}
      </div>

      <div className="lf-suggestion-actions">
        <Button variant="secondary" size="sm" onClick={() => onDecide(suggestion.id, "reject")}>
          Dismiss
        </Button>
        <Button variant="primary" size="sm" onClick={() => onDecide(suggestion.id, "approve")}>
          Accept
        </Button>
      </div>
    </article>
  );
}
