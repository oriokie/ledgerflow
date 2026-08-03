import { ArrowLeft, Inbox } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import type { TenantRow } from "../../api/platform";
import { ApiError } from "../../api/client";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import { ReasonDialog } from "../../components/admin/AdminShell";
import {
  useInvoices,
  useCapability,
  usePlatformMe,
  usePlatformPlans,
  useStartImpersonation,
  useTenant,
  useTenantAction,
  useTenants,
} from "../../hooks/usePlatform";
import {
  Eyebrow,
  Badge,
  Button,
  Card,
  EmptyState,
  Grid,
  Heading,
  Input,
  LoadingBlock,
  Select,
  Stack,
  Table,
  Text,
  useToast,
} from "../../ui";
import { bytes, day, humanize, money } from "./format";

function statusTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "active") return "success";
  if (status === "trialing") return "neutral";
  if (status === "past_due" || status === "incomplete") return "warning";
  if (status === "canceled") return "danger";
  return "neutral";
}

export function AdminTenantsPage() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const { data, isLoading } = useTenants({ q: query, status, page });

  const columns = [
    {
      key: "name",
      header: "Workspace",
      render: (row: TenantRow) => (
        <Stack gap={1}>
          <Link to={`/admin/tenants/${row.id}`} className="lf-admin-link">
            {row.name}
          </Link>
          <Text size="xs" tone="tertiary">
            {row.owner_email || "No owner on record"}
          </Text>
        </Stack>
      ),
    },
    {
      key: "plan",
      header: "Plan",
      render: (row: TenantRow) => (
        <Stack gap={1}>
          <span>{row.plan_name || "—"}</span>
          {row.subscription_status && (
            <Badge tone={statusTone(row.subscription_status)}>
              {row.subscription_status.replace(/_/g, " ")}
            </Badge>
          )}
        </Stack>
      ),
    },
    {
      key: "mrr",
      header: "MRR",
      align: "right" as const,
      render: (row: TenantRow) => money(row.mrr_minor, row.currency),
    },
    {
      key: "members",
      header: "Seats",
      align: "right" as const,
      hideMobile: true,
      render: (row: TenantRow) => String(row.member_count),
    },
    {
      key: "country",
      header: "Country",
      hideMobile: true,
      render: (row: TenantRow) => row.country || "—",
    },
    {
      key: "state",
      header: "State",
      render: (row: TenantRow) =>
        row.is_active ? <Badge tone="success">Active</Badge> : <Badge tone="danger">Suspended</Badge>,
    },
    {
      key: "created",
      header: "Joined",
      hideMobile: true,
      render: (row: TenantRow) => day(row.created_at),
    },
  ];

  return (
    <Stack gap={4}>
      <AdminPageHeader
        title="Customers"
        description="Every workspace on the platform. Open one to see its subscription, usage and the support actions your role allows."
        meta={data ? `${data.count} workspace${data.count === 1 ? "" : "s"}` : undefined}
      />

      <div className="lf-admin-toolbar">
        {/* Wrapped rather than classed: Input's className lands on the inner
            <input>, and the toolbar sizes its flex children. */}
        <div className="lf-admin-toolbar-search">
          <Input
            label="Search"
            placeholder="Workspace, billing email, or member email"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
          />
        </div>
        <Select
          label="State"
          value={status}
          options={[
            { value: "", label: "All" },
            { value: "active", label: "Active" },
            { value: "suspended", label: "Suspended" },
          ]}
          onChange={(event) => {
            setStatus(event.target.value);
            setPage(1);
          }}
        />
      </div>

      {isLoading && !data ? (
        <LoadingBlock label="Loading customers…" />
      ) : !data?.results.length ? (
        <EmptyState icon={Inbox} title="No customers match" body="Try widening the filters." />
      ) : (
        <>
          <Table
            columns={columns}
            rows={data.results}
            rowKey={(row) => row.id}
            caption="Customer workspaces"
            responsive
            stickyHeader
          />
          <div className="lf-admin-pagination">
            <Text size="sm" tone="secondary">
              {data.count} workspace{data.count === 1 ? "" : "s"}
            </Text>
            <div className="lf-inline lf-gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={!data.previous}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={!data.next}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </Stack>
  );
}

type PendingAction =
  | { kind: "suspend" }
  | { kind: "reactivate" }
  | { kind: "close" }
  | { kind: "reset-billing" }
  | { kind: "extend-trial" }
  | { kind: "cancel-subscription" }
  | { kind: "change-plan" }
  | { kind: "complimentary" }
  | { kind: "credit" }
  | { kind: "impersonate" }
  | null;

const ACTION_COPY: Record<string, { title: string; confirm: string; destructive?: boolean }> = {
  suspend: { title: "Suspend workspace", confirm: "Suspend", destructive: true },
  reactivate: { title: "Reactivate workspace", confirm: "Reactivate" },
  close: { title: "Close workspace", confirm: "Close workspace", destructive: true },
  "reset-billing": { title: "Reset billing state", confirm: "Reset" },
  "extend-trial": { title: "Extend trial", confirm: "Extend" },
  "cancel-subscription": { title: "Cancel subscription", confirm: "Cancel subscription", destructive: true },
  "change-plan": { title: "Change plan", confirm: "Change plan" },
  complimentary: { title: "Grant complimentary subscription", confirm: "Grant" },
  credit: { title: "Issue account credit", confirm: "Issue credit" },
  impersonate: { title: "Open customer workspace", confirm: "Start session", destructive: true },
};

export function AdminTenantDetailPage() {
  const { tenantId = "" } = useParams();
  const { data: staff } = usePlatformMe();
  const can = useCapability(staff);
  const { data: tenant, isLoading } = useTenant(tenantId);
  // The first question an operator opens this page with is almost always a
  // billing question; eight invoices answer most of them without a jump to the
  // Invoices screen and its filters.
  const { data: invoices } = useInvoices({ tenant_id: tenantId, page_size: 8 });
  const { data: plans } = usePlatformPlans();
  const action = useTenantAction(tenantId);
  const impersonate = useStartImpersonation(tenantId);
  const toast = useToast();

  const [pending, setPending] = useState<PendingAction>(null);
  const [planId, setPlanId] = useState("");
  const [days, setDays] = useState("14");
  const [months, setMonths] = useState("1");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (isLoading) return <LoadingBlock label="Loading workspace…" />;
  if (!tenant) return <EmptyState icon={Inbox} title="Not found" body="No such workspace." />;

  const close = () => {
    setPending(null);
    setError(null);
  };

  const onConfirm = async (reason: string) => {
    if (!pending) return;
    setError(null);
    try {
      if (pending.kind === "impersonate") {
        const grant = await impersonate.mutateAsync({ reason, read_only: true });
        // The grant token is returned once and deliberately not persisted
        // anywhere it could be recovered from.
        toast(
          `Session started — read-only, expires ${new Date(grant.expires_at).toLocaleTimeString()}`,
          { tone: "success" },
        );
      } else {
        const body: Record<string, unknown> = { reason };
        if (pending.kind === "extend-trial") body.days = Number(days);
        if (pending.kind === "change-plan") body.plan_id = planId;
        if (pending.kind === "complimentary") {
          body.plan_id = planId;
          body.months = Number(months);
        }
        if (pending.kind === "credit") {
          body.amount_minor = Math.round(Number(amount) * 100);
          body.currency = tenant.currency;
        }
        await action.mutateAsync({ action: pending.kind, body });
        toast(`${"Done"} — ${"The action was recorded in the audit log."}`, { tone: "success" });
      }
      close();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Something went wrong.");
    }
  };

  const copy = pending ? ACTION_COPY[pending.kind] : null;
  const sub = tenant.subscription;

  return (
    <Stack gap={4}>
      {/* The list is the only way back besides the sidebar, and an operator
          moving through several accounts does it dozens of times a day. */}
      <Link className="lf-admin-backlink" to="/admin/tenants">
        <ArrowLeft size={14} aria-hidden /> All customers
      </Link>

      <div className="lf-admin-page-head">
        <div className="lf-admin-page-head-text">
          <div className="lf-admin-page-title-row">
            <Heading level={1}>{tenant.name}</Heading>
            {tenant.is_active ? (
              <Badge tone="success">Active</Badge>
            ) : (
              <Badge tone="danger">Suspended</Badge>
            )}
          </div>
          <Text size="sm" tone="secondary">
            {humanize(tenant.type)} · {tenant.country || "Country not stated"} · {tenant.currency} ·{" "}
            {tenant.timezone}
          </Text>
        </div>
        {can("tenant.impersonate") && (
          <div className="lf-admin-page-actions">
            <Button variant="secondary" onClick={() => setPending({ kind: "impersonate" })}>
              Open workspace
            </Button>
          </div>
        )}
      </div>

      <Grid cols={4} gap={3}>
        <Card title="Subscription">
          {sub ? (
            <Stack gap={2}>
              <div className="lf-admin-kv">
                <span>Plan</span>
                <strong>{sub.plan_name}</strong>
              </div>
              <div className="lf-admin-kv">
                <span>Status</span>
                <Badge tone={statusTone(sub.status)}>{sub.status.replace(/_/g, " ")}</Badge>
              </div>
              <div className="lf-admin-kv">
                <span>MRR</span>
                <strong>{money(sub.mrr_minor, sub.currency)}</strong>
              </div>
              {sub.trial_end && (
                <div className="lf-admin-kv">
                  <span>Trial ends</span>
                  <span>{day(sub.trial_end)}</span>
                </div>
              )}
              {sub.current_period_end && (
                <div className="lf-admin-kv">
                  <span>Renews</span>
                  <span>{day(sub.current_period_end)}</span>
                </div>
              )}
            </Stack>
          ) : (
            <Text size="sm" tone="tertiary">
              No subscription.
            </Text>
          )}
        </Card>

        <Card title="Usage">
          <Stack gap={2}>
            <div className="lf-admin-kv">
              <span>Members</span>
              <strong>{tenant.usage.member_count}</strong>
            </div>
            <div className="lf-admin-kv">
              <span>Accounts</span>
              <strong>{tenant.usage.account_count}</strong>
            </div>
            <div className="lf-admin-kv">
              <span>Transactions</span>
              <strong>{tenant.usage.transaction_count.toLocaleString()}</strong>
            </div>
            <div className="lf-admin-kv">
              <span>Storage</span>
              <strong>{bytes(tenant.usage.storage_bytes)}</strong>
            </div>
            <Text size="xs" tone="tertiary">
              {tenant.usage.captured_at
                ? `Snapshot taken ${day(tenant.usage.captured_at)}.`
                : "No usage snapshot captured yet."}
            </Text>
          </Stack>
        </Card>

        <Card title="Members">
          <ul className="lf-admin-member-list">
            {tenant.members.map((member) => (
              <li key={member.id}>
                <div>
                  <strong>{member.name || member.email}</strong>
                  <Text size="xs" tone="tertiary">
                    {member.email}
                  </Text>
                </div>
                <Badge tone="neutral">{member.role}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      </Grid>

      {invoices && invoices.results.length > 0 && (
        <Card title="Recent invoices" ruledHeader action={<Link to="/admin/invoices">All invoices</Link>}>
          <table className="lf-admin-mini-table">
            <thead>
              <tr>
                <th>Invoice</th>
                <th>Status</th>
                <th className="lf-admin-mini-amount">Total</th>
                <th>Issued</th>
              </tr>
            </thead>
            <tbody>
              {invoices.results.map((invoice) => (
                <tr key={invoice.id}>
                  <td>{invoice.number}</td>
                  <td>
                    <Badge tone={statusTone(invoice.status)}>{humanize(invoice.status)}</Badge>
                  </td>
                  <td className="lf-admin-mini-amount">{money(invoice.total_minor, invoice.currency)}</td>
                  <td>{day(invoice.issue_date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Card title="Actions" ruledHeader>
        <Text size="sm" tone="secondary">
          Every action here is recorded against this account with your name and the reason you give.
        </Text>

        {/* Grouped by how much they can hurt. The old layout was one row of
            nine buttons in which "Extend trial" sat beside "Close workspace" —
            severity was carried by button colour alone, and colour is never
            allowed to be the only carrier. */}
        {(can("subscription.write") || can("subscription.grant") || can("credit.issue")) && (
          <Stack gap={2}>
            <Eyebrow>Billing</Eyebrow>
            <div className="lf-admin-actions">
              {can("subscription.write") && (
                <>
                  <Button variant="secondary" onClick={() => setPending({ kind: "extend-trial" })}>
                    Extend trial
                  </Button>
                  <Button variant="secondary" onClick={() => setPending({ kind: "change-plan" })}>
                    Change plan
                  </Button>
                  <Button variant="secondary" onClick={() => setPending({ kind: "reset-billing" })}>
                    Reset billing state
                  </Button>
                </>
              )}
              {can("subscription.grant") && (
                <Button variant="secondary" onClick={() => setPending({ kind: "complimentary" })}>
                  Grant complimentary
                </Button>
              )}
              {can("credit.issue") && (
                <Button variant="secondary" onClick={() => setPending({ kind: "credit" })}>
                  Issue credit
                </Button>
              )}
            </div>
          </Stack>
        )}

        {(can("tenant.suspend") || can("subscription.write") || can("tenant.delete")) && (
          <div className="lf-admin-danger-zone">
            <Eyebrow>Danger zone</Eyebrow>
            <Text size="xs" tone="tertiary">
              These change what the customer can do or pay. Each asks for a reason.
            </Text>
            <div className="lf-admin-actions">
              {can("subscription.write") && (
                <Button
                  variant="secondary"
                  onClick={() => setPending({ kind: "cancel-subscription" })}
                >
                  Cancel subscription
                </Button>
              )}
              {can("tenant.suspend") &&
                (tenant.is_active ? (
                  <Button variant="danger" onClick={() => setPending({ kind: "suspend" })}>
                    Suspend
                  </Button>
                ) : (
                  <Button variant="primary" onClick={() => setPending({ kind: "reactivate" })}>
                    Reactivate
                  </Button>
                ))}
              {can("tenant.delete") && (
                <Button variant="danger" onClick={() => setPending({ kind: "close" })}>
                  Close workspace
                </Button>
              )}
            </div>
          </div>
        )}
      </Card>

      {pending && copy && (
        <ReasonDialog
          open
          title={copy.title}
          confirmLabel={copy.confirm}
          destructive={copy.destructive}
          minLength={pending.kind === "impersonate" ? 10 : 5}
          pending={action.isPending || impersonate.isPending}
          error={error}
          onClose={close}
          onConfirm={onConfirm}
          description={
            pending.kind === "impersonate"
              ? "You will see this household's financial data. The session is read-only, expires automatically, and every request is logged."
              : undefined
          }
        >
          {pending.kind === "extend-trial" && (
            <Input
              label="Days"
              type="number"
              min={1}
              value={days}
              onChange={(event) => setDays(event.target.value)}
            />
          )}
          {(pending.kind === "change-plan" || pending.kind === "complimentary") && (
            <Select
              label="Plan"
              value={planId}
              placeholder="Choose a plan"
              options={(plans ?? []).map((plan) => ({
                value: plan.id,
                label: `${plan.name} — ${money(plan.price_minor, plan.currency)}/${plan.interval}`,
              }))}
              onChange={(event) => setPlanId(event.target.value)}
            />
          )}
          {pending.kind === "complimentary" && (
            <Input
              label="Months"
              type="number"
              min={1}
              value={months}
              onChange={(event) => setMonths(event.target.value)}
            />
          )}
          {pending.kind === "credit" && (
            <Input
              label={`Amount (${tenant.currency})`}
              type="number"
              min={0}
              step="0.01"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          )}
        </ReasonDialog>
      )}
    </Stack>
  );
}
