import { useEffect, useMemo, useState } from "react";
import { ApiError } from "../../api/client";
import type {
  CashflowStackLine,
  DecisionFinding,
  DecisionResult,
  Position,
  QuestionMeta,
  Verdict,
} from "../../api/projections";
import { advisorApi } from "../../api/projections";
import { formatAmount } from "../../lib/money";
import { Badge, Banner, Button, Card, FormField, Input, Select, Stack, Text } from "../../ui";
import { decisionFieldDefaults, scenarioHints } from "./scenarioHints";

/** Money fields are typed in whole units; rates as percentages. Same rule as
 * the scenario builder, and for the same reason: people say "5,000", not
 * "500000", and "9%", not "0.09". */
function isMoney(name: string) {
  return name.endsWith("_minor");
}
function toWire(name: string, raw: string): number {
  const n = Number(raw);
  if (Number.isNaN(n)) return 0;
  if (isMoney(name)) return Math.round(n * 100);
  if (name.endsWith("_rate") || name.endsWith("_return")) return n / 100;
  return n;
}

function labelFor(name: string): string {
  const base = name.replace(/_minor$/, "").replace(/_/g, " ");
  if (name.endsWith("_rate") || name.endsWith("_return")) return `${base} (%)`;
  if (name.includes("year")) return `${base} (years)`;
  if (name.includes("month")) return `${base} (months)`;
  return base;
}

const VERDICT_TONE: Record<Verdict, "success" | "warning" | "danger" | "neutral"> = {
  yes: "success",
  yes_with_care: "success",
  tight: "warning",
  no: "danger",
  unknown: "neutral",
};

const VERDICT_LABEL: Record<Verdict, string> = {
  yes: "Yes",
  yes_with_care: "Yes, with care",
  tight: "Tight",
  no: "No",
  unknown: "Can't tell yet",
};

const CONFIDENCE_LABEL: Record<string, string> = {
  measured: "Measured",
  mixed: "Part measured, part assumed",
  assumed: "Mostly assumption",
};

function FindingList({ items, currency }: { items: DecisionFinding[]; currency: string }) {
  return (
    <ul className="lf-finding-list">
      {items.map((f) => (
        <li key={f.label}>
          <Text size="sm" weight="medium">
            {f.label}
            {f.amount_minor !== null ? ` — ${formatAmount(f.amount_minor, currency)}` : ""}
          </Text>
          <Text size="sm" tone="secondary">
            {f.text}
          </Text>
        </li>
      ))}
    </ul>
  );
}

function Answer({ result }: { result: DecisionResult }) {
  const { currency } = result;
  return (
    <Stack gap={4}>
      <div className="lf-verdict">
        <Badge tone={VERDICT_TONE[result.verdict]}>{VERDICT_LABEL[result.verdict]}</Badge>
        <Text size="md" weight="semibold">
          {result.headline}
        </Text>
        <Badge tone="neutral">{CONFIDENCE_LABEL[result.confidence] ?? result.confidence}</Badge>
      </div>

      {result.explanation.paragraphs.map((p) => (
        <Text key={p} size="sm">
          {p}
        </Text>
      ))}

      {/* Whether a model touched the wording is the user's business. */}
      {result.explanation.llm_used && (
        <Text size="xs" tone="tertiary">
          The wording above was drafted by a language model. Every figure in it was computed
          here and checked against the calculation before it was shown.
        </Text>
      )}
      {result.explanation.rejected_reason && (
        <Text size="xs" tone="tertiary">
          A model draft was discarded because {result.explanation.rejected_reason}. The
          explanation above is the calculation's own.
        </Text>
      )}

      {result.because.length > 0 && (
        <section>
          <Text size="sm" weight="semibold">
            What it turns on
          </Text>
          <FindingList items={result.because} currency={currency} />
        </section>
      )}
      {result.costs.length > 0 && (
        <section>
          <Text size="sm" weight="semibold">
            What it costs
          </Text>
          <FindingList items={result.costs} currency={currency} />
        </section>
      )}
      {result.risks.length > 0 && (
        <section>
          <Text size="sm" weight="semibold">
            What could go wrong
          </Text>
          <FindingList items={result.risks} currency={currency} />
        </section>
      )}
      {result.alternatives.length > 0 && (
        <section>
          <Text size="sm" weight="semibold">
            Worth considering instead
          </Text>
          <FindingList items={result.alternatives} currency={currency} />
        </section>
      )}

      <details className="lf-assumption-details">
        <summary>
          <Text size="sm" tone="secondary" as="span">
            What this assumed ({result.assumptions.length})
          </Text>
        </summary>
        <ul className="lf-assumption-list">
          {result.assumptions.map((a) => (
            <li key={a}>
              <Text size="sm" tone="secondary">
                {a}
              </Text>
            </li>
          ))}
        </ul>
      </details>

      <Text size="xs" tone="tertiary">
        This is decision support, not financial advice — a calculation with its workings
        shown, so you can disagree with the assumptions rather than the conclusion.
      </Text>
    </Stack>
  );
}

/**
 * The named questions, with forms rendered from the backend's own schema.
 *
 * Nothing here knows that a mortgage has a rate or that retirement has a
 * withdrawal rate — the same discipline as the scenario builder, so a sixth
 * question is a backend change alone.
 */
export function DecisionAssistant({
  position,
  stack,
}: {
  position?: Position;
  stack?: CashflowStackLine[];
}) {
  const [questions, setQuestions] = useState<QuestionMeta[]>([]);
  const [slug, setSlug] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [result, setResult] = useState<DecisionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    advisorApi
      .questions()
      .then(({ results }) => {
        setQuestions(results);
        if (results.length) setSlug(results[0].slug);
      })
      .catch(() => setError("Couldn't load the questions."));
  }, []);

  useEffect(() => {
    if (!slug || !position) return;
    setValues(decisionFieldDefaults(slug, scenarioHints(position, stack ?? []), position));
  }, [slug, position, stack]);

  const selected = useMemo(() => questions.find((q) => q.slug === slug), [questions, slug]);

  const ask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    setAsking(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {};
      for (const field of selected.fields) {
        const raw = values[field.name];
        if (raw === undefined || raw === "") continue;
        body[field.name] = toWire(field.name, raw);
      }
      setResult(await advisorApi.ask(slug, body));
    } catch (err) {
      setResult(null);
      setError(err instanceof ApiError ? err.detail : "Couldn't answer that.");
    } finally {
      setAsking(false);
    }
  };

  return (
    <Stack gap={4}>
      <Card title="Ask a question">
        <form onSubmit={ask}>
          {error && <Banner tone="danger">{error}</Banner>}
          <FormField label="Question" htmlFor="decision-question">
            <Select
              id="decision-question"
              value={slug}
              onChange={(e) => {
                setSlug(e.target.value);
                setResult(null);
              }}
            >
              {questions.map((q) => (
                <option key={q.slug} value={q.slug}>
                  {q.question}
                </option>
              ))}
            </Select>
          </FormField>
          <div className="lf-scenario-form-grid">
            {selected?.fields.map((field) => (
              <FormField
                key={field.name}
                label={labelFor(field.name)}
                htmlFor={`decision-${field.name}`}
                hint={field.required ? "Required" : undefined}
              >
                <Input
                  id={`decision-${field.name}`}
                  type="number"
                  step="any"
                  required={field.required}
                  amount={isMoney(field.name)}
                  value={values[field.name] ?? ""}
                  onChange={(e) => setValues({ ...values, [field.name]: e.target.value })}
                />
              </FormField>
            ))}
          </div>
          <Button type="submit" disabled={asking || !selected}>
            {asking ? "Working it out…" : "Answer this"}
          </Button>
        </form>
      </Card>

      {result && (
        <Card title={result.question}>
          <Answer result={result} />
        </Card>
      )}
    </Stack>
  );
}
