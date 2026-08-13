import { Trash2 } from "lucide-react";
import { useState } from "react";
import type { IncomeSource } from "../../api/income";
import { Badge, Button, Card, ConfirmAction, Figure, FigureRow, Text } from "../../ui";
import { FREQUENCY_LABEL, KIND_LABEL, RELIABILITY_LABEL } from "./incomeCopy";
import { RecordReceiptForm } from "./RecordReceiptForm";

/**
 * One income source.
 *
 * The card's job is to show, at a glance, whether the number it displays was
 * *measured* or *typed*. That distinction is the whole point of recording
 * receipts, and burying it would make the feature decorative.
 */
export function IncomeSourceCard({
  source,
  onDelete,
}: {
  source: IncomeSource;
  onDelete: (id: string) => void | Promise<void>;
}) {
  const {
    currency,
    expected_net_minor,
    expected_is_observed,
    monthly_net_minor,
    variance_pct,
    receipt_count,
    is_speculative,
  } = source;

  const [recording, setRecording] = useState(false);

  return (
    <Card
      title={source.name}
      action={
        <ConfirmAction
          label="Remove"
          icon={<Trash2 size={15} strokeWidth={2} />}
          /* Soft delete on the server: past receipts survive, so the history
             every past figure was derived from stays intact. */
          confirmLabel="Remove"
          cancelLabel="Keep"
          onConfirm={() => onDelete(source.id)}
        />
      }
    >
      <div className="lf-inline lf-gap-2">
        <Badge tone="neutral">{KIND_LABEL[source.kind]}</Badge>
        <Badge tone={source.reliability === "fixed" ? "success" : "warning"}>
          {RELIABILITY_LABEL[source.reliability]}
        </Badge>
        {source.payer && (
          <Text size="sm" tone="tertiary">
            {source.payer}
          </Text>
        )}
        {!source.is_current && (
          <Badge tone="warning">{source.ends_on ? "Ended" : "Not started"}</Badge>
        )}
      </div>

      {/* Two figures, not three.

          Swing used to sit beside the expected amount as its own column. Three
          duospace money figures inside a half-width card overflowed their own
          containers — the amounts are `nowrap`, so the box scrolled instead,
          which axe correctly reports as a scrollable region no keyboard can
          reach. Folding swing into the hint fixes the layout and is the better
          reading anyway: the spread is a property *of* the expected figure,
          not a sibling of it. */}
      <FigureRow>
        {is_speculative ? (
          <Figure
            label="Expected"
            amountMinor={expected_net_minor}
            currency={currency}
            neutral
            certainty="speculative"
            // The type system requires this string. It is the reason the
            // speculative variant exists: a figure nobody promised, with no
            // history behind it, may not be drawn as a bare numeral.
            confidence={
              receipt_count === 0
                ? "You marked this irregular and haven't recorded any payments yet — this is the amount you entered, not a measurement."
                : `Only ${receipt_count} payment${receipt_count > 1 ? "s" : ""} recorded, which is too few to average.`
            }
            hint={FREQUENCY_LABEL[source.frequency]}
          />
        ) : (
          <Figure
            label="Expected"
            amountMinor={expected_net_minor}
            currency={currency}
            neutral
            certainty="projected"
            hint={
              expected_is_observed
                ? `Average of ${receipt_count} payments${
                    variance_pct !== null ? ` · ±${variance_pct}%` : ""
                  }`
                : FREQUENCY_LABEL[source.frequency]
            }
          />
        )}

        {monthly_net_minor !== null ? (
          <Figure
            label="Per month"
            amountMinor={monthly_net_minor}
            currency={currency}
            neutral
            certainty="projected"
          />
        ) : (
          <Figure label="Per month" value="—" hint="No set schedule" />
        )}

      </FigureRow>

      {expected_is_observed && expected_net_minor !== source.stated_net_minor && (
        <Text size="sm" tone="secondary">
          You entered{" "}
          {new Intl.NumberFormat(undefined, {
            style: "currency",
            currency,
            maximumFractionDigits: 0,
          }).format(source.stated_net_minor / 100)}
          . The figure above is what you have actually been paid.
        </Text>
      )}

      {recording ? (
        <RecordReceiptForm
          sourceId={source.id}
          currency={currency}
          onDone={() => setRecording(false)}
          onCancel={() => setRecording(false)}
        />
      ) : (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setRecording(true)}
          style={{ marginTop: "var(--lf-space-3)" }}
        >
          Record a payment
        </Button>
      )}
    </Card>
  );
}
