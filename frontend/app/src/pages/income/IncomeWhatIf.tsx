import { useState } from "react";
import type { IncomeSource } from "../../api/income";
import { useIncomeStress } from "../../hooks/useIncome";
import { Figure, FigureRow, Text } from "../../ui";

/**
 * Counterfactual committed income if this stream stopped.
 *
 * Hidden until asked for so the card stays a record of the source, not a
 * simulation. Ad-hoc streams have no monthly equivalent and are omitted —
 * inventing one would be a guess dressed as a plan.
 */
export function IncomeWhatIf({ source }: { source: IncomeSource }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useIncomeStress(source.id, open);

  if (source.monthly_net_minor == null) return null;

  return (
    <div className="lf-income-whatif">
      <button
        type="button"
        className="lf-insight-why-toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {open ? "Hide what-if" : "If this stops"}
      </button>
      {open && (
        <div className="lf-income-whatif-body">
          {isLoading && (
            <Text size="sm" tone="tertiary">
              Working the numbers…
            </Text>
          )}
          {!isLoading && data == null && (
            <Text size="sm" tone="secondary">
              We need a monthly income position before this scenario means anything.
            </Text>
          )}
          {data && (
            <>
              <Text size="sm" tone="secondary">
                {data.sentence}
              </Text>
              <FigureRow>
                <Figure
                  label="Income left"
                  amountMinor={data.after.monthly_income_minor}
                  currency={data.currency}
                  neutral
                  hint={`was ${new Intl.NumberFormat(undefined, {
                    style: "currency",
                    currency: data.currency,
                    maximumFractionDigits: 0,
                  }).format(data.before.monthly_income_minor / 100)}`}
                />
                <Figure
                  label="Then committed"
                  value={
                    data.after.committed_pct == null ? "—" : `${Math.round(data.after.committed_pct)}%`
                  }
                  hint={
                    data.before.committed_pct == null
                      ? undefined
                      : `was ${Math.round(data.before.committed_pct)}%`
                  }
                  tone={data.after.shortfall_minor > 0 ? "critical" : "default"}
                />
                {data.after.shortfall_minor > 0 && (
                  <Figure
                    label="Shortfall"
                    amountMinor={data.after.shortfall_minor}
                    currency={data.currency}
                    tone="critical"
                  />
                )}
              </FigureRow>
            </>
          )}
        </div>
      )}
    </div>
  );
}
