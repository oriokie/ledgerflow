import { useMemo, useState } from "react";
import { ApiError } from "../../api/client";
import type { EventKindMeta, Scenario, ScenarioEvent } from "../../api/projections";
import { projectionsApi } from "../../api/projections";
import {
  Badge,
  Banner,
  Button,
  Card,
  ConfirmAction,
  FormField,
  Input,
  Select,
  Switch,
  Text,
} from "../../ui";

/** Parameter names ending in `_minor` are money and are typed in whole units —
 * people say "5,000", not "500000". Everything else is a plain number, except
 * rates, which are typed as percentages and sent as fractions. */
function isMoney(name: string) {
  return name.endsWith("_minor");
}
function isRate(name: string) {
  return name.startsWith("annual_") || name.endsWith("_fraction") || name.endsWith("_growth");
}

function toWire(name: string, raw: string): number | string {
  const n = Number(raw);
  if (Number.isNaN(n)) return raw;
  if (isMoney(name)) return Math.round(n * 100);
  if (isRate(name)) return n / 100;
  return n;
}

function fromWire(name: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  if (isMoney(name)) return String(n / 100);
  if (isRate(name)) return String(n * 100);
  return String(n);
}

function unitFor(name: string) {
  if (isMoney(name)) return "amount";
  if (isRate(name)) return "%";
  if (name.includes("month")) return "months";
  if (name.includes("year")) return "years";
  return "";
}

interface Props {
  scenario: Scenario;
  catalogue: EventKindMeta[];
  onChanged: () => void;
}

/**
 * The form for adding a life event, rendered entirely from the backend's
 * parameter schema. Nothing here knows that a mortgage has a rate or that a
 * child has a support duration — adding a sixteenth life event is a backend
 * change and this picks it up for free.
 */
export function ScenarioBuilder({ scenario, catalogue, onChanged }: Props) {
  const [kind, setKind] = useState(catalogue[0]?.kind ?? "");
  const [startMonth, setStartMonth] = useState("1");
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const selected = useMemo(() => catalogue.find((c) => c.kind === kind), [catalogue, kind]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    setSaving(true);
    setError(null);
    try {
      const params: Record<string, unknown> = {};
      for (const spec of selected.params) {
        const raw = values[spec.name];
        if (raw === undefined || raw === "") continue;
        params[spec.name] = toWire(spec.name, raw);
      }
      await projectionsApi.addEvent(scenario.id, {
        kind,
        start_month: Number(startMonth) || 1,
        params,
      });
      setValues({});
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't add that event.");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (event: ScenarioEvent) => {
    await projectionsApi.deleteEvent(scenario.id, event.id);
    onChanged();
  };

  const toggle = async (event: ScenarioEvent) => {
    await projectionsApi.updateEvent(scenario.id, event.id, { is_enabled: !event.is_enabled });
    onChanged();
  };

  return (
    <Card title="What happens">
      {scenario.events.length > 0 && (
        <ul className="lf-event-list">
          {scenario.events.map((event) => (
            <li key={event.id} className="lf-event-row">
              <div className="lf-event-row-main">
                <Text size="sm" weight="medium">
                  {event.label}
                </Text>
                <Badge tone="neutral">month {event.start_month}</Badge>
                {!event.is_enabled && <Badge tone="warning">muted</Badge>}
              </div>
              <div className="lf-event-row-actions">
                {/* No visible label: the row already names the event, and a
                    second copy of the name would be noise for sighted users
                    and a repetition for screen readers. */}
                <Switch
                  checked={event.is_enabled}
                  onChange={() => toggle(event)}
                  aria-label={`Include ${event.label} in this scenario`}
                />
                <ConfirmAction
                  label="Remove"
                  confirmLabel="Remove"
                  cancelLabel="Keep"
                  size="sm"
                  onConfirm={() => remove(event)}
                />
              </div>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={submit} className="lf-scenario-form">
        {error && <Banner tone="danger">{error}</Banner>}
        <div className="lf-scenario-form-grid">
          <FormField label="Life event" htmlFor="event-kind">
            <Select
              id="event-kind"
              value={kind}
              onChange={(e) => {
                setKind(e.target.value);
                setValues({});
              }}
            >
              {catalogue.map((c) => (
                <option key={c.kind} value={c.kind}>
                  {c.label}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Starting in month" htmlFor="event-start">
            <Input
              id="event-start"
              type="number"
              min={1}
              max={scenario.horizon_months}
              value={startMonth}
              onChange={(e) => setStartMonth(e.target.value)}
            />
          </FormField>
          {selected?.params.map((spec) => (
            <FormField
              key={spec.name}
              label={`${spec.name.replace(/_minor$/, "").replace(/_/g, " ")}${
                unitFor(spec.name) && unitFor(spec.name) !== "amount"
                  ? ` (${unitFor(spec.name)})`
                  : ""
              }`}
              htmlFor={`param-${spec.name}`}
              hint={spec.required ? "Required" : undefined}
            >
              <Input
                id={`param-${spec.name}`}
                type="number"
                step="any"
                required={spec.required}
                amount={isMoney(spec.name)}
                value={values[spec.name] ?? fromWire(spec.name, spec.default)}
                onChange={(e) => setValues({ ...values, [spec.name]: e.target.value })}
              />
            </FormField>
          ))}
        </div>
        <Button type="submit" disabled={saving}>
          {saving ? "Adding…" : "Add to scenario"}
        </Button>
      </form>
    </Card>
  );
}
