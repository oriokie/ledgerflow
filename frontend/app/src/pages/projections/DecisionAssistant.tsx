import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
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
import { downloadFilePost } from "../../lib/download";
import { formatAmount } from "../../lib/money";
import {
  Badge,
  Banner,
  Button,
  Card,
  FormField,
  Inline,
  Input,
  Select,
  Stack,
  Text,
  useToast,
} from "../../ui";
import { decisionFieldDefaults, isPercentField, scenarioHints } from "./scenarioHints";

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
  if (isPercentField(name)) return n / 100;
  return n;
}

function labelFor(name: string): string {
  const base = name.replace(/_minor$/, "").replace(/_/g, " ");
  const titled = base.charAt(0).toUpperCase() + base.slice(1);
  if (isPercentField(name)) return `${titled} (%)`;
  // "years" already says the unit. "term_years" would otherwise read "Term years (years)".
  if (name.includes("year") && !base.endsWith("year") && !base.endsWith("years")) return `${titled} (years)`;
  if (name.includes("month") && !base.endsWith("month") && !base.endsWith("months")) return `${titled} (months)`;
  return titled;
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

export function Answer({ result }: { result: DecisionResult }) {
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
        LedgerFlow is an educational decision-support tool, not licensed financial
        advice. Figures are calculations from the inputs and assumptions shown.
      </Text>
    </Stack>
  );
}

function TakeHomeActions({ slug, body }: { slug: string; body: Record<string, unknown> }) {
  const toast = useToast();
  const [busy, setBusy] = useState<"pdf" | "xlsx" | "share" | null>(null);
  const [shareUrl, setShareUrl] = useState<string | null>(null);

  const run = async (kind: "pdf" | "xlsx" | "share") => {
    setBusy(kind);
    try {
      if (kind === "share") {
        const { url } = await advisorApi.share(slug, body);
        setShareUrl(url);
        try {
          await navigator.clipboard.writeText(url);
          toast("Link copied. Anyone with it can view this result for seven days.", {
            tone: "success",
          });
        } catch {
          toast("Share link ready — copy it from the field below.", { tone: "info" });
        }
        return;
      }
      const ext = kind === "pdf" ? "pdf" : "xlsx";
      await downloadFilePost(
        `/projections/questions/${slug}/export.${ext}`,
        `ledgerflow-${slug}.${ext}`,
        body,
      );
    } catch (err) {
      toast(err instanceof ApiError ? err.detail : "Couldn't prepare that file.", { tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <Stack gap={2}>
      <Inline gap={2} wrap>
        <Button variant="secondary" loading={busy === "pdf"} onClick={() => run("pdf")}>
          Download PDF
        </Button>
        <Button variant="secondary" loading={busy === "xlsx"} onClick={() => run("xlsx")}>
          Download Excel
        </Button>
        <Button variant="ghost" loading={busy === "share"} onClick={() => run("share")}>
          Copy share link
        </Button>
      </Inline>
      {shareUrl && (
        <Input readOnly value={shareUrl} aria-label="Share link" onFocus={(e) => e.target.select()} />
      )}
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
  stated = false,
}: {
  position?: Position;
  stack?: CashflowStackLine[];
  /** Figures were typed for a try, not read from a workspace. */
  stated?: boolean;
}) {
  const [questions, setQuestions] = useState<QuestionMeta[]>([]);
  const [slug, setSlug] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [result, setResult] = useState<DecisionResult | null>(null);
  const [lastBody, setLastBody] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [ratesAsOf, setRatesAsOf] = useState<string | null>(null);

  useEffect(() => {
    const questions = stated ? advisorApi.guestQuestions : advisorApi.questions;
    const rates = stated ? advisorApi.guestRates : advisorApi.kenyaRates;
    questions()
      .then(({ results }) => {
        setQuestions(results);
        if (results.length) setSlug(results[0].slug);
      })
      .catch(() => setError("Couldn't load the questions."));
    rates().then((r) => setRatesAsOf(r.as_of)).catch(() => {});
  }, [stated]);

  useEffect(() => {
    if (!slug || !position) return;
    setValues(decisionFieldDefaults(slug, scenarioHints(position, stack ?? []), position));
    // A guest's typed figures change on every keystroke. Re-applying defaults
    // then would wipe the question they are in the middle of filling in.
    // Reset inputs still reads the latest position.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, stated ? null : position, stack]);

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
      setLastBody(body);
      setResult(
        stated
          ? await advisorApi.guestAsk(slug, {
              position: {
                currency: position?.currency ?? "KES",
                monthly_net_income_minor: position?.monthly_net_income_minor ?? 0,
                monthly_expenses_minor: position?.monthly_expenses_minor ?? 0,
                liquid_minor: position?.liquid_minor ?? 0,
              },
              inputs: body,
            })
          : await advisorApi.ask(slug, body),
      );
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
                setLastBody(null);
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
                hint={
                  field.name === "overrun_buffer"
                    ? "Percent of the construction cost. 20 means a fifth, not a shilling amount."
                    : field.required
                      ? "Required"
                      : undefined
                }
              >
                <Input
                  id={`decision-${field.name}`}
                  type="number"
                  step="any"
                  required={field.required}
                  amount={isMoney(field.name)}
                  value={values[field.name] ?? ""}
                  onChange={(e) => {
                    const next = e.target.value;
                    setValues((prev) => ({ ...prev, [field.name]: next }));
                  }}
                />
              </FormField>
            ))}
          </div>
          <Inline gap={2} wrap>
            <Button type="submit" disabled={asking || !selected}>
              {asking ? "Working it out…" : "Answer this"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={!selected}
              onClick={() => {
                if (!selected) return;
                setValues(
                  position
                    ? decisionFieldDefaults(slug, scenarioHints(position, stack ?? []), position)
                    : {},
                );
                setResult(null);
                setLastBody(null);
              }}
            >
              Reset inputs
            </Button>
          </Inline>
          {ratesAsOf && (
            <Text size="xs" tone="tertiary">
              Kenya statutory and conveyancing rates as of {ratesAsOf}. Every rate is an
              editable input, not a locked figure.
            </Text>
          )}
        </form>
      </Card>

      {result && lastBody && (
        <Card title={result.question}>
          <Stack gap={4}>
            <Answer result={result} />
            {stated ? (
              <Stack gap={2}>
                <Text size="sm" tone="secondary">
                  This used the figures you typed. Nothing was saved. A workspace measures the
                  same question from your own records, and you can take the answer with you.
                </Text>
                <Inline gap={2} wrap>
                  <Link className="lf-btn lf-btn--primary" to="/register">
                    Create a workspace
                  </Link>
                  <Link className="lf-btn lf-btn--ghost" to="/login">
                    Sign in
                  </Link>
                </Inline>
              </Stack>
            ) : (
              <TakeHomeActions slug={slug} body={lastBody} />
            )}
          </Stack>
        </Card>
      )}
    </Stack>
  );
}
