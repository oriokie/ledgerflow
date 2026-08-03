import { Check, X } from "lucide-react";
import type { CategorizationSuggestion } from "../../api/types";
import { Button, Card, Inline } from "../../ui";
import { confidenceLabel } from "./insightsCopy";

/** A categorization suggestion phrased as a question, not a confidence score —
 * "looks like this belongs in X, file it there?" with an honest sureness cue. */
export function SuggestionCard({
  suggestion,
  categoryName,
  onAccept,
  onReject,
  pending,
}: {
  suggestion: CategorizationSuggestion;
  categoryName: string | undefined;
  onAccept: () => void;
  onReject: () => void;
  pending: boolean;
}) {
  return (
    <Card>
      <p className="lf-suggest-q">
        Looks like this belongs in <strong>{categoryName ?? "a category"}</strong>. Want to file it there?
      </p>
      <p className="lf-suggest-meta">
        {confidenceLabel(suggestion.confidence)}
        {suggestion.rationale ? ` · ${suggestion.rationale}` : ""}
      </p>
      <Inline gap={2} style={{ marginTop: "var(--lf-space-3)" }}>
        <Button variant="secondary" size="sm" icon={<Check size={14} />} disabled={pending} onClick={onAccept}>
          Yes, file it
        </Button>
        <Button variant="ghost" size="sm" icon={<X size={14} />} disabled={pending} onClick={onReject}>
          Not quite
        </Button>
      </Inline>
    </Card>
  );
}
