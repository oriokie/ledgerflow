import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import type { AskAnswer, CalibrationReport, Twin } from "../../api/projections";
import { twinApi } from "../../api/projections";
import { formatAmount } from "../../lib/money";
import { Badge, Banner, Button, Card, FormField, Input, Meter, Stack, Text } from "../../ui";

const CONFIDENCE_LABEL: Record<string, string> = {
  none: "Nothing measured yet",
  weak: "Early — the standard assumptions still lead",
  moderate: "Blended with your own figures",
  strong: "Your own figures",
};

const TREND_LABEL: Record<string, string> = {
  improving: "getting closer",
  steady: "holding steady",
  worse: "drifting further out",
};

function percent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

/** What the product has measured about this household, and how much of it is
 * evidence rather than a default we shipped. */
function Measurements({ twin }: { twin: Twin }) {
  return (
    <Card title="What this knows about you">
      <Stack gap={3}>
        <div className="lf-risk-row">
          <Text size="md" weight="semibold">
            {CONFIDENCE_LABEL[twin.confidence]}
          </Text>
          <Badge tone={twin.confidence === "strong" ? "success" : "neutral"}>
            {twin.months_observed} month{twin.months_observed === 1 ? "" : "s"} on record
          </Badge>
        </div>
        <ul className="lf-finding-list">
          {twin.parameters.map((p) => (
            <li key={p.key}>
              <div className="lf-risk-row">
                <Text size="sm" weight="medium">
                  {p.label}
                </Text>
                <Text size="sm" tone="secondary">
                  {p.measured === null ? "not measured" : percent(p.measured)}
                  {p.differs_from_prior && p.measured !== null ? " (differs from the default)" : ""}
                </Text>
              </div>
              <Text size="sm" tone="secondary">
                {p.detail}
              </Text>
            </li>
          ))}
        </ul>
        {twin.notes.map((n) => (
          <Text key={n} size="xs" tone="tertiary">
            {n}
          </Text>
        ))}
      </Stack>
    </Card>
  );
}

/** How well the product has been predicting — including badly. */
function Calibration({
  report,
  onRecord,
}: {
  report: CalibrationReport;
  onRecord: () => void;
}) {
  return (
    <Card title="How well this has predicted you">
      <Stack gap={3}>
        <Text size="md" weight="semibold">
          {report.headline}
        </Text>
        {report.overall_median_error !== null && (
          <Meter
            // Inverted: a smaller error is a better score, and a meter that
            // fills as the product gets worse would read exactly backwards.
            value={Math.max(0, Math.round((1 - report.overall_median_error) * 100))}
            caption={`Typically within ${percent(report.overall_median_error)} of the outcome`}
            aria-label="Forecast accuracy"
          />
        )}
        <ul className="lf-finding-list">
          {report.kinds.map((k) => (
            <li key={k.kind}>
              <div className="lf-risk-row">
                <Text size="sm" weight="medium">
                  {k.label}
                </Text>
                <Text size="sm" tone="secondary">
                  {k.samples === 0 ? "no marks yet" : percent(k.median_error)}
                  {k.trend ? ` · ${TREND_LABEL[k.trend]}` : ""}
                </Text>
              </div>
              <Text size="sm" tone="secondary">
                {k.detail}
              </Text>
            </li>
          ))}
        </ul>
        <Button variant="secondary" size="sm" onClick={onRecord}>
          Score closed months and forecast the next one
        </Button>
        {report.notes.map((n) => (
          <Text key={n} size="xs" tone="tertiary">
            {n}
          </Text>
        ))}
      </Stack>
    </Card>
  );
}

/** Ask in words. Routes to the same evaluators the forms use. */
function Ask() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setAsking(true);
    setError(null);
    try {
      setAnswer(await twinApi.ask(question.trim()));
    } catch (err) {
      setAnswer(null);
      setError(err instanceof ApiError ? err.detail : "Couldn't answer that.");
    } finally {
      setAsking(false);
    }
  };

  return (
    <Card title="Ask about your money">
      <form onSubmit={submit}>
        {error && <Banner tone="danger">{error}</Banner>}
        <FormField
          label="Your question"
          htmlFor="twin-question"
          hint="For example: can I afford a house at 4,500,000 with a 900,000 deposit at 9%?"
        >
          <Input
            id="twin-question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Can we afford a second home?"
          />
        </FormField>
        <Button type="submit" disabled={asking || !question.trim()}>
          {asking ? "Working it out…" : "Ask"}
        </Button>
      </form>

      {answer && !answer.answered && (
        <Banner tone="info">
          <Text size="sm">{answer.detail}</Text>
        </Banner>
      )}

      {answer?.answered && (
        <Stack gap={3}>
          <Text size="xs" tone="tertiary">
            Understood as “{answer.understood_as}”. Every figure below was computed from your
            ledger, not written by a model.
          </Text>
          <Text size="md" weight="semibold">
            {answer.headline}
          </Text>
          {answer.explanation?.paragraphs.map((p) => (
            <Text key={p} size="sm">
              {p}
            </Text>
          ))}
          <ul className="lf-finding-list">
            {(answer.because ?? []).map((f) => (
              <li key={f.label}>
                <Text size="sm" weight="medium">
                  {f.label}
                  {f.amount_minor !== null && answer.currency
                    ? ` — ${formatAmount(f.amount_minor, answer.currency)}`
                    : ""}
                </Text>
                <Text size="sm" tone="secondary">
                  {f.text}
                </Text>
              </li>
            ))}
          </ul>
        </Stack>
      )}
    </Card>
  );
}

/** The twin surface: what it knows, how well it has predicted, and asking. */
export function TwinPanel() {
  const [twin, setTwin] = useState<Twin | null>(null);
  const [report, setReport] = useState<CalibrationReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const [t, c] = await Promise.all([twinApi.get(), twinApi.calibration()]);
      setTwin(t);
      setReport(c);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't load the twin.");
    }
  };

  useEffect(() => {
    load();
  }, []);

  const record = async () => {
    await twinApi.recordForecast();
    await load();
  };

  if (error) return <Banner tone="warning">{error}</Banner>;

  return (
    <Stack gap={5}>
      <Ask />
      {twin && <Measurements twin={twin} />}
      {report && <Calibration report={report} onRecord={record} />}
    </Stack>
  );
}
