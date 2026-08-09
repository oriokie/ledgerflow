import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { ApiError } from "../../api/client";
import type { AutomationClause, AutomationRule } from "../../api/types";
import { useCategories } from "../../hooks/useFinance";
import { useCreateAutomationRule, useUpdateAutomationRule } from "../../hooks/useIntelligence";
import { Badge, Banner, Button, Checkbox, IconButton, Inline, Input, Modal, SegmentedControl, Stack } from "../../ui";

// Matches automation.py's closed vocabulary exactly. Hardcoded rather than
// fetched: it's a small, rarely-changing set, and adding an endpoint just to
// list it would be indirection for its own sake.
const FIELDS = [
  { value: "memo", label: "Memo" },
  { value: "payee_normalized", label: "Payee" },
  { value: "amount_minor", label: "Amount (minor units)" },
  { value: "currency", label: "Currency" },
  { value: "account_type", label: "Account type" },
  { value: "category_id", label: "Category" },
] as const;

const OPS = [
  { value: "contains", label: "contains" },
  { value: "startswith", label: "starts with" },
  { value: "eq", label: "equals" },
  { value: "regex", label: "matches regex" },
  { value: "gte", label: "≥" },
  { value: "lte", label: "≤" },
  { value: "abs_gte", label: "≥ (absolute value)" },
  { value: "abs_lte", label: "≤ (absolute value)" },
] as const;

const ACTION_TYPES = [
  { value: "set_category", label: "Set category" },
  { value: "add_tag", label: "Add tag" },
  { value: "flag_review", label: "Flag for review" },
] as const;

type ClauseDraft = { field: string; op: string; value: string };
type ActionDraft = { type: string; category_id?: string; name?: string; reason?: string };

function toDraft(c: AutomationClause): ClauseDraft {
  return { field: c.field, op: c.op, value: String(c.value) };
}

function clausesFromRule(rule?: AutomationRule | null): { match: "all" | "any"; clauses: ClauseDraft[] } {
  if (!rule) return { match: "all", clauses: [{ field: "memo", op: "contains", value: "" }] };
  if (rule.conditions.any) return { match: "any", clauses: rule.conditions.any.map(toDraft) };
  return { match: "all", clauses: (rule.conditions.all ?? []).map(toDraft) };
}

function actionsFromRule(rule?: AutomationRule | null): ActionDraft[] {
  if (!rule || rule.actions.length === 0) return [{ type: "set_category" }];
  return rule.actions.map((a) => ({
    type: String(a.type),
    category_id: typeof a.category_id === "string" ? a.category_id : undefined,
    name: typeof a.name === "string" ? a.name : undefined,
    reason: typeof a.reason === "string" ? a.reason : undefined,
  }));
}

/** Create or edit a rule. One form for both — an edit is just a create
 * pre-filled from the existing rule, and keeping them apart would mean two
 * places for the same condition/action builder to drift. */
export function RuleForm({ editing, onClose }: { editing?: AutomationRule | null; onClose: () => void }) {
  const { data: categories } = useCategories();
  const create = useCreateAutomationRule();
  const update = useUpdateAutomationRule();

  const initial = clausesFromRule(editing);
  const [name, setName] = useState(editing?.name ?? "");
  const [priority, setPriority] = useState(String(editing?.priority ?? 100));
  const [stopProcessing, setStopProcessing] = useState(editing?.stop_processing ?? false);
  const [match, setMatch] = useState<"all" | "any">(initial.match);
  const [clauses, setClauses] = useState<ClauseDraft[]>(initial.clauses);
  const [actions, setActions] = useState<ActionDraft[]>(actionsFromRule(editing));
  const [sampleText, setSampleText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const assignableCategories = categories?.filter((c) => c.kind !== "transfer") ?? [];
  const isPending = create.isPending || update.isPending;

  const updateClause = (i: number, patch: Partial<ClauseDraft>) =>
    setClauses((prev) => prev.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  const updateAction = (i: number, patch: Partial<ActionDraft>) =>
    setActions((prev) => prev.map((a, j) => (j === i ? { ...a, ...patch } : a)));

  const save = async () => {
    setError(null);
    if (!name.trim()) return setError("Name the rule.");
    const cleanClauses = clauses.filter((c) => c.value.trim() !== "");
    if (cleanClauses.length === 0) return setError("Add at least one condition.");
    const conditions = match === "all" ? { all: cleanClauses } : { any: cleanClauses };

    const cleanActions = actions
      .map((a) => {
        if (a.type === "set_category")
          return a.category_id ? { type: "set_category", category_id: a.category_id } : null;
        if (a.type === "add_tag") return a.name?.trim() ? { type: "add_tag", name: a.name.trim() } : null;
        if (a.type === "flag_review")
          return { type: "flag_review", ...(a.reason?.trim() ? { reason: a.reason.trim() } : {}) };
        return null;
      })
      .filter((a): a is NonNullable<typeof a> => a !== null);
    if (cleanActions.length === 0) return setError("Add at least one complete action.");

    const payload = {
      name,
      conditions,
      actions: cleanActions,
      priority: Number(priority) || 100,
      stop_processing: stopProcessing,
    };

    try {
      if (editing) await update.mutateAsync({ ruleId: editing.id, ...payload });
      else await create.mutateAsync(payload);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't save this rule.");
    }
  };

  // Instant feedback on a regex condition, before the round trip that would
  // otherwise be the only way to find out a pattern doesn't do what it looks
  // like it does.
  const regexClause = clauses.find((c) => c.op === "regex" && c.value.trim());
  let regexPreview: boolean | null = null;
  if (regexClause && sampleText.trim()) {
    try {
      regexPreview = new RegExp(regexClause.value, "i").test(sampleText);
    } catch {
      regexPreview = null;
    }
  }

  return (
    <Modal open onClose={onClose} title={editing ? "Edit rule" : "New rule"} size="lg">
      <Stack gap={4}>
        <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. Parking" />

        <div>
          <p className="lf-label">When</p>
          <SegmentedControl
            legend="Match"
            value={match}
            onChange={setMatch}
            options={[
              { value: "all", label: "All of these" },
              { value: "any", label: "Any of these" },
            ]}
          />
          <Stack gap={2} style={{ marginTop: "var(--lf-space-2)" }}>
            {clauses.map((clause, i) => (
              <Inline key={i} gap={2} wrap={false}>
                <select
                  className="lf-select"
                  aria-label={`Condition ${i + 1} field`}
                  value={clause.field}
                  onChange={(e) => updateClause(i, { field: e.target.value })}
                >
                  {FIELDS.map((f) => (
                    <option key={f.value} value={f.value}>
                      {f.label}
                    </option>
                  ))}
                </select>
                <select
                  className="lf-select"
                  aria-label={`Condition ${i + 1} operator`}
                  value={clause.op}
                  onChange={(e) => updateClause(i, { op: e.target.value })}
                >
                  {OPS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <input
                  className="lf-input"
                  aria-label={`Condition ${i + 1} value`}
                  value={clause.value}
                  onChange={(e) => updateClause(i, { value: e.target.value })}
                  placeholder="value"
                />
                <IconButton
                  label="Remove condition"
                  icon={<Trash2 size={14} />}
                  disabled={clauses.length <= 1}
                  onClick={() => setClauses((prev) => prev.filter((_, j) => j !== i))}
                />
              </Inline>
            ))}
          </Stack>
          <Button
            variant="ghost"
            size="sm"
            style={{ marginTop: "var(--lf-space-2)" }}
            onClick={() => setClauses((prev) => [...prev, { field: "memo", op: "contains", value: "" }])}
          >
            <Plus size={14} aria-hidden="true" /> Condition
          </Button>

          {regexClause && (
            <div style={{ marginTop: "var(--lf-space-3)" }}>
              <Input
                label="Test the regex condition against sample text"
                value={sampleText}
                onChange={(e) => setSampleText(e.target.value)}
                placeholder="Paste a memo to check the pattern"
              />
              {regexPreview !== null && (
                <Badge tone={regexPreview ? "success" : "neutral"}>{regexPreview ? "Matches" : "No match"}</Badge>
              )}
            </div>
          )}
        </div>

        <div>
          <p className="lf-label">Then</p>
          <Stack gap={2}>
            {actions.map((action, i) => (
              <Inline key={i} gap={2} wrap={false}>
                <select
                  className="lf-select"
                  aria-label={`Action ${i + 1} type`}
                  value={action.type}
                  onChange={(e) => updateAction(i, { type: e.target.value })}
                >
                  {ACTION_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
                {action.type === "set_category" && (
                  <select
                    className="lf-select"
                    aria-label={`Action ${i + 1} category`}
                    value={action.category_id ?? ""}
                    onChange={(e) => updateAction(i, { category_id: e.target.value })}
                  >
                    <option value="">Choose category…</option>
                    {assignableCategories.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                )}
                {action.type === "add_tag" && (
                  <input
                    className="lf-input"
                    aria-label={`Action ${i + 1} tag name`}
                    value={action.name ?? ""}
                    onChange={(e) => updateAction(i, { name: e.target.value })}
                    placeholder="Tag name"
                  />
                )}
                {action.type === "flag_review" && (
                  <input
                    className="lf-input"
                    aria-label={`Action ${i + 1} reason`}
                    value={action.reason ?? ""}
                    onChange={(e) => updateAction(i, { reason: e.target.value })}
                    placeholder="Reason (optional)"
                  />
                )}
                <IconButton
                  label="Remove action"
                  icon={<Trash2 size={14} />}
                  disabled={actions.length <= 1}
                  onClick={() => setActions((prev) => prev.filter((_, j) => j !== i))}
                />
              </Inline>
            ))}
          </Stack>
          <Button
            variant="ghost"
            size="sm"
            style={{ marginTop: "var(--lf-space-2)" }}
            onClick={() => setActions((prev) => [...prev, { type: "set_category" }])}
          >
            <Plus size={14} aria-hidden="true" /> Action
          </Button>
        </div>

        <Inline gap={4} wrap={false}>
          <Input
            label="Priority"
            type="number"
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            hint="Lower runs first"
            style={{ maxWidth: 120 }}
          />
          <Checkbox
            label="Stop other rules once this one matches"
            checked={stopProcessing}
            onChange={(e) => setStopProcessing(e.target.checked)}
          />
        </Inline>

        {error && <Banner tone="danger">{error}</Banner>}
        <Button variant="primary" onClick={save} loading={isPending}>
          {editing ? "Save changes" : "Create rule"}
        </Button>
      </Stack>
    </Modal>
  );
}
