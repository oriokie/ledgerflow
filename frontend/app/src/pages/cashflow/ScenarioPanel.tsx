import { useState } from "react";
import { api, ApiError } from "../../api/client";
import { formatAmount } from "../../lib/money";
import { Banner, Button, Card, Input, Text } from "../../ui";

interface ScenarioLeg {
  safe_to_spend_minor: number | null;
  first_negative_on: string | null;
  lowest_balance_minor: number | null;
  fi_years: number | null;
  fi_number_minor: number | null;
}

interface ScenarioResult {
  currency: string;
  baseline: ScenarioLeg;
  scenario: ScenarioLeg;
  notes: string[];
}

/**
 * The advisor's modelling session: "what if rent goes up? what if I save
 * more?" — answered by re-running the real projections, never by adjusting a
 * displayed number. Inputs are whole currency units (people think in "5,000
 * more", not minor units); the API speaks minor.
 */
export function ScenarioPanel() {
  const [incomeDelta, setIncomeDelta] = useState("");
  const [expenseDelta, setExpenseDelta] = useState("");
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const body = await api.post<ScenarioResult>("/analytics/scenarios/preview/", {
        monthly_income_delta_minor: Math.round((Number(incomeDelta) || 0) * 100),
        monthly_expense_delta_minor: Math.round((Number(expenseDelta) || 0) * 100),
      });
      setResult(body);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't run that scenario.");
    } finally {
      setLoading(false);
    }
  };

  const fmtDate = (iso: string | null) =>
    iso
      ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" })
      : "never in this window";

  const row = (
    label: string,
    render: (leg: ScenarioLeg) => string,
  ): { label: string; before: string; after: string } | null =>
    result ? { label, before: render(result.baseline), after: render(result.scenario) } : null;

  const rows = result
    ? [
        row("Safe to spend", (leg) =>
          leg.safe_to_spend_minor === null
            ? "—"
            : formatAmount(leg.safe_to_spend_minor, result.currency),
        ),
        row("Balance first negative", (leg) => fmtDate(leg.first_negative_on)),
        row("Work optional in", (leg) =>
          leg.fi_years === null ? "beyond any horizon" : `${leg.fi_years} yrs`,
        ),
        row("FI number", (leg) =>
          leg.fi_number_minor === null ? "—" : formatAmount(leg.fi_number_minor, result.currency),
        ),
      ].filter((entry): entry is NonNullable<typeof entry> => entry !== null)
    : [];

  return (
    <Card title="What if…">
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-3)" }}>
        <Text tone="secondary" size="sm">
          Model a change before you make it — a raise, a rent rise, a cut. The projections re-run
          with the change applied; nothing is saved.
        </Text>
        <div style={{ display: "flex", gap: "var(--lf-space-3)", flexWrap: "wrap" }}>
          <Input
            label="Monthly income change"
            type="number"
            value={incomeDelta}
            placeholder="e.g. 5000"
            onChange={(e) => setIncomeDelta(e.target.value)}
          />
          <Input
            label="Monthly spending change"
            type="number"
            value={expenseDelta}
            placeholder="e.g. 3000 or -2000"
            onChange={(e) => setExpenseDelta(e.target.value)}
          />
          <div style={{ alignSelf: "flex-end" }}>
            <Button variant="primary" loading={loading} onClick={run}>
              Preview
            </Button>
          </div>
        </div>

        {error && <Banner tone="danger">{error}</Banner>}

        {result && (
          <>
            <table className="lf-scenario-table">
              <thead>
                <tr>
                  <th scope="col" aria-label="Measure" />
                  <th scope="col">Today</th>
                  <th scope="col">With the change</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => (
                  <tr key={entry.label}>
                    <th scope="row">{entry.label}</th>
                    <td>{entry.before}</td>
                    <td data-changed={entry.before !== entry.after || undefined}>{entry.after}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {result.notes.map((note) => (
              <Text key={note} tone="tertiary" size="xs">
                {note}
              </Text>
            ))}
          </>
        )}
      </div>
    </Card>
  );
}
