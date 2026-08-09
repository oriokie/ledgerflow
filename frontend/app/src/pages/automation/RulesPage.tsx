import { Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
import { useState } from "react";
import type { AutomationClause, AutomationRule } from "../../api/types";
import {
  useAutomationRules,
  useDeleteAutomationRule,
  useUpdateAutomationRule,
} from "../../hooks/useIntelligence";
import {
  Button,
  Card,
  ConfirmAction,
  EmptyState,
  IconButton,
  PageHeader,
  SkeletonCard,
  Switch,
  Table,
  Text,
} from "../../ui";
import type { Column } from "../../ui";
import { RuleForm } from "./RuleForm";

function summarizeConditions(rule: AutomationRule): string {
  const clauses: AutomationClause[] = rule.conditions.all ?? rule.conditions.any ?? [];
  const joiner = rule.conditions.any ? " or " : " and ";
  if (clauses.length === 0) return "No conditions";
  return clauses.map((c) => `${c.field} ${c.op} "${c.value}"`).join(joiner);
}

function summarizeActions(rule: AutomationRule): string {
  return rule.actions
    .map((a) => {
      if (a.type === "set_category") return "set category";
      if (a.type === "add_tag") return `tag "${String(a.name ?? "")}"`;
      if (a.type === "flag_review") return "flag for review";
      return String(a.type);
    })
    .join(", ");
}

/** Rule management — the create/edit/delete counterpart to the review queue
 * (`AutomationPage`), which only ever shows *system-detected* findings. A
 * rule is something the user wrote themselves, in advance, so it's a
 * different surface even though both live under "Automation". */
export function RulesPage({ embedded }: { embedded?: boolean } = {}) {
  const { data: rules, isLoading } = useAutomationRules();
  const setActive = useUpdateAutomationRule();
  const deleteRule = useDeleteAutomationRule();
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<AutomationRule | null>(null);

  const list = rules ?? [];

  const newRuleButton = (
    <Button variant="primary" onClick={() => setShowCreate(true)}>
      <Plus size={15} aria-hidden="true" /> New rule
    </Button>
  );

  const columns: Column<AutomationRule>[] = [
    {
      key: "name",
      header: "Rule",
      render: (r) => (
        <div>
          <span className="lf-cell-primary">{r.name}</span>
          <div className="lf-cell-meta">
            If {summarizeConditions(r)}, then {summarizeActions(r)}.
          </div>
        </div>
      ),
    },
    {
      key: "priority",
      header: "Priority",
      hideMobile: true,
      render: (r) => <span className="lf-cell-meta">{r.priority}</span>,
    },
    {
      key: "matches",
      header: "Matched",
      hideMobile: true,
      render: (r) => (
        <span className="lf-cell-meta">
          {r.match_count} time{r.match_count === 1 ? "" : "s"}
        </span>
      ),
    },
    {
      key: "active",
      header: "Active",
      render: (r) => (
        <Switch
          label={r.is_active ? "On" : "Off"}
          checked={r.is_active}
          onChange={(e) => setActive.mutate({ ruleId: r.id, is_active: e.target.checked })}
        />
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (r) => (
        <div className="lf-row-actions">
          <IconButton label={`Edit ${r.name}`} icon={<Pencil size={15} />} onClick={() => setEditing(r)} />
          <ConfirmAction
            label={`Delete ${r.name}`}
            icon={<Trash2 size={15} />}
            confirmLabel="Delete"
            cancelLabel="Keep"
            disabled={deleteRule.isPending}
            onConfirm={() => deleteRule.mutate(r.id)}
          />
        </div>
      ),
    },
  ];

  return (
    <>
      {!embedded && (
        <PageHeader
          eyebrow="Automation"
          title="Rules"
          description="If a transaction's memo, payee, amount, or category matches, LedgerFlow does this automatically."
          actions={newRuleButton}
        />
      )}
      {/* The hub owns the page title when embedded and hides page-level
          actions along with it (matching every other embedded tab in this
          app) — but unlike those read-mostly tabs, this one needs a reachable
          create action, so it gets a small standalone bar instead of going
          silent. */}
      {embedded && (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "var(--lf-space-3)" }}>
          {newRuleButton}
        </div>
      )}

      {isLoading && <SkeletonCard />}

      {!isLoading && list.length === 0 && (
        <Card>
          <EmptyState
            icon={Sparkles}
            title="No rules yet"
            body="Write a rule once and it applies to every matching transaction from then on — e.g. anything mentioning PARKNGO becomes Parking automatically."
            action={
              <Button variant="primary" onClick={() => setShowCreate(true)}>
                Create a rule
              </Button>
            }
          />
        </Card>
      )}

      {!isLoading && list.length > 0 && (
        <Table columns={columns} rows={list} rowKey={(r) => r.id} responsive={false} caption="Automation rules" />
      )}

      {!isLoading && list.length > 0 && (
        <Text tone="tertiary" size="xs" style={{ marginTop: "var(--lf-space-3)" }}>
          Rules run automatically on new and imported transactions. Use "Apply rules now" on the Transactions page
          to run them retroactively.
        </Text>
      )}

      {(showCreate || editing) && (
        <RuleForm
          editing={editing}
          onClose={() => {
            setShowCreate(false);
            setEditing(null);
          }}
        />
      )}
    </>
  );
}
