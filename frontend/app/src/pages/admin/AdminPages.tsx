import { Inbox } from "lucide-react";
import { Link } from "react-router-dom";
import { useState } from "react";

import { ApiError } from "../../api/client";
import type {
  HealthSnapshot,
  AuditRow,
  Coupon,
  DunningCase,
  Invoice,
  PaymentRow,
  PlatformStaff,
  Refund,
} from "../../api/platform";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import { ReasonDialog } from "../../components/admin/AdminShell";
import {
  useAcknowledgeNotification,
  useAppointStaff,
  useAuditLog,
  useCapability,
  useCoupons,
  useCreateCoupon,
  useDeactivateCoupon,
  useDecideRefund,
  useDownloadInvoice,
  useDunningAction,
  useDunningCases,
  useHealth,
  useInvoices,
  usePayments,
  usePlatformMe,
  usePlatformNotifications,
  usePlatformStaff,
  useRefunds,
  useRevokeStaff,
  useSendInvoice,
} from "../../hooks/usePlatform";
import {
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Figure,
  FigureRow,
  Grid,
  Input,
  LoadingBlock,
  Modal,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  useToast,
} from "../../ui";
import { day, humanize, moment, money } from "./format";

function tone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (["paid", "succeeded", "ok", "recovered", "active"].includes(status)) return "success";
  if (["pending", "processing", "requested", "approved", "degraded", "open", "trialing"].includes(status))
    return "warning";
  if (["failed", "overdue", "rejected", "down", "abandoned", "suspended", "past_due"].includes(status))
    return "danger";
  return "neutral";
}

// ==================================================================== billing
export function AdminBillingPage() {
  const [tab, setTab] = useState("payments");
  return (
    <Stack gap={4}>
      <AdminPageHeader
        title="Billing"
        description="Every charge and refund on the platform. Refunds are dual-control: one person requests, a different person releases the money."
      />
      <Tabs
        label="Billing sections"
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "payments", label: "Payments" },
          { value: "refunds", label: "Refunds" },
        ]}
      />
      {tab === "payments" ? <PaymentsPanel /> : <RefundsPanel />}
    </Stack>
  );
}

function PaymentsPanel() {
  const [status, setStatus] = useState("");
  const { data, isLoading } = usePayments({ status });

  const columns = [
    {
      key: "amount",
      header: "Amount",
      align: "right" as const,
      render: (row: PaymentRow) => money(row.amount_minor, row.currency),
    },
    {
      key: "status",
      header: "Status",
      render: (row: PaymentRow) => <Badge tone={tone(row.status)}>{row.status}</Badge>,
    },
    { key: "provider", header: "Provider", render: (row: PaymentRow) => row.provider },
    {
      key: "reason",
      header: "Detail",
      hideMobile: true,
      render: (row: PaymentRow) =>
        row.failure_reason ? humanize(row.failure_reason) : row.description || "—",
    },
    {
      key: "created",
      header: "When",
      render: (row: PaymentRow) => moment(row.created_at),
    },
  ];

  return (
    <Stack gap={3}>
      <div className="lf-admin-toolbar">
        <Select
          label="Status"
          value={status}
          options={[
            { value: "", label: "All" },
            { value: "succeeded", label: "Succeeded" },
            { value: "pending", label: "Pending" },
            { value: "failed", label: "Failed" },
            { value: "refunded", label: "Refunded" },
          ]}
          onChange={(event) => setStatus(event.target.value)}
        />
      </div>
      {isLoading && !data ? (
        <LoadingBlock />
      ) : data?.results.length ? (
        <Table columns={columns} rows={data.results} rowKey={(r) => r.id} responsive stickyHeader />
      ) : (
        <Card>
          <EmptyState icon={Inbox} title="No payments" body="Nothing matches this filter." />
        </Card>
      )}
    </Stack>
  );
}

function RefundsPanel() {
  const { data: staff } = usePlatformMe();
  const can = useCapability(staff);
  const { data, isLoading } = useRefunds();
  const decide = useDecideRefund();
  const toast = useToast();
  const [pending, setPending] = useState<{ refund: Refund; decision: "approve" | "reject" } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onConfirm = async (note: string) => {
    if (!pending) return;
    setError(null);
    try {
      await decide.mutateAsync({ id: pending.refund.id, decision: pending.decision, note });
      toast(`Refund ${pending.decision}d`, { tone: "success" });
      setPending(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Something went wrong.");
    }
  };

  const columns = [
    {
      key: "amount",
      header: "Amount",
      align: "right" as const,
      render: (row: Refund) => money(row.amount_minor, row.currency),
    },
    {
      key: "status",
      header: "Status",
      render: (row: Refund) => <Badge tone={tone(row.status)}>{row.status}</Badge>,
    },
    { key: "reason", header: "Reason", render: (row: Refund) => row.reason },
    {
      key: "requested",
      header: "Requested by",
      hideMobile: true,
      render: (row: Refund) => row.requested_by_email || "—",
    },
    {
      key: "actions",
      header: "",
      render: (row: Refund) =>
        row.status === "requested" && can("refund.approve") ? (
          <div className="lf-inline lf-gap-2">
            <Button size="sm" onClick={() => setPending({ refund: row, decision: "approve" })}>
              Approve
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setPending({ refund: row, decision: "reject" })}
            >
              Reject
            </Button>
          </div>
        ) : (
          <Text size="xs" tone="tertiary">
            {row.failure_reason || row.decision_note || "—"}
          </Text>
        ),
    },
  ];

  return (
    <Stack gap={3}>
      <Text size="sm" tone="secondary">
        If the Approve button is absent, your role can request refunds but not release the money.
      </Text>
      {isLoading && !data ? (
        <LoadingBlock />
      ) : data?.results.length ? (
        <Table columns={columns} rows={data.results} rowKey={(r) => r.id} responsive stickyHeader />
      ) : (
        <Card>
          <EmptyState icon={Inbox} title="No refunds" body="Nothing to review." />
        </Card>
      )}

      {pending && (
        <ReasonDialog
          open
          title={pending.decision === "approve" ? "Approve refund" : "Reject refund"}
          confirmLabel={pending.decision === "approve" ? "Approve and pay" : "Reject"}
          destructive={pending.decision === "approve"}
          pending={decide.isPending}
          error={error}
          onClose={() => setPending(null)}
          onConfirm={onConfirm}
          description={
            pending.decision === "approve"
              ? `${money(pending.refund.amount_minor, pending.refund.currency)} will be returned to the customer.`
              : undefined
          }
        />
      )}
    </Stack>
  );
}

// =================================================================== invoices
export function AdminInvoicesPage() {
  const [status, setStatus] = useState("");
  const { data, isLoading } = useInvoices({ status });
  const { data: staff } = usePlatformMe();
  const can = useCapability(staff);
  const download = useDownloadInvoice();
  const send = useSendInvoice();
  const toast = useToast();

  const columns = [
    { key: "number", header: "Invoice", render: (row: Invoice) => row.number },
    {
      key: "tenant",
      header: "Customer",
      render: (row: Invoice) =>
        row.tenant_name ? (
          <Link className="lf-admin-tenant-link" to={`/admin/tenants/${row.tenant_id}`}>
            {row.tenant_name}
          </Link>
        ) : (
          // The workspace is gone but its invoices are not — they are financial
          // records. Saying so beats an em dash the operator has to investigate.
          <Text size="sm" tone="tertiary">deleted workspace</Text>
        ),
    },
    {
      key: "status",
      header: "Status",
      render: (row: Invoice) => <Badge tone={tone(row.status)}>{humanize(row.status)}</Badge>,
    },
    {
      key: "total",
      header: "Total",
      align: "right" as const,
      render: (row: Invoice) => money(row.total_minor, row.currency),
    },
    {
      key: "due",
      header: "Due",
      align: "right" as const,
      render: (row: Invoice) => money(row.amount_due_minor, row.currency),
    },
    {
      key: "issued",
      header: "Issued",
      hideMobile: true,
      render: (row: Invoice) => day(row.issue_date),
    },
    {
      key: "duedate",
      header: "Due date",
      hideMobile: true,
      render: (row: Invoice) => day(row.due_date),
    },
    {
      key: "actions",
      header: "",
      render: (row: Invoice) => (
        <div className="lf-inline lf-gap-2">
          <Button
            size="sm"
            variant="ghost"
            disabled={download.isPending}
            onClick={async () => {
              // The download is silent by nature — the browser saves the file
              // with no visible change to the page, which reads as a dead
              // button. Say what happened.
              try {
                await download.mutateAsync({ id: row.id, number: row.number });
                toast(`${row.number}.pdf downloaded`, { tone: "success" });
              } catch (err) {
                toast(err instanceof ApiError ? err.detail : "Could not generate the PDF.");
              }
            }}
          >
            {download.isPending ? "Preparing…" : "PDF"}
          </Button>
          {can("invoice.write") && row.status !== "draft" && (
            <Button
              size="sm"
              variant="ghost"
              disabled={send.isPending}
              onClick={async () => {
                try {
                  const result = await send.mutateAsync({ id: row.id });
                  toast(`Queued for ${result.to}`, { tone: "success" });
                } catch (err) {
                  toast(err instanceof ApiError ? err.detail : "Could not send.");
                }
              }}
            >
              Email
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <Stack gap={4}>
      <AdminPageHeader
        title="Invoices"
        description="Issued documents, not projections. Sending re-delivers the PDF the customer already has; nothing here changes an amount."
        meta={data ? `${data.count} invoice${data.count === 1 ? "" : "s"}` : undefined}
      />
      <div className="lf-admin-toolbar">
        <Select
          label="Status"
          value={status}
          options={[
            { value: "", label: "All" },
            { value: "draft", label: "Draft" },
            { value: "pending", label: "Pending" },
            { value: "paid", label: "Paid" },
            { value: "overdue", label: "Overdue" },
            { value: "cancelled", label: "Cancelled" },
            { value: "refunded", label: "Refunded" },
          ]}
          onChange={(event) => setStatus(event.target.value)}
        />
      </div>
      {isLoading && !data ? (
        <LoadingBlock />
      ) : data?.results.length ? (
        <Table columns={columns} rows={data.results} rowKey={(r) => r.id} responsive stickyHeader />
      ) : (
        <Card>
          <EmptyState icon={Inbox} title="No invoices" body="Nothing matches this filter." />
        </Card>
      )}
    </Stack>
  );
}

// ==================================================================== dunning
export function AdminDunningPage() {
  const [status, setStatus] = useState("open");
  const { data, isLoading } = useDunningCases({ status });
  const act = useDunningAction();
  const toast = useToast();
  const [pending, setPending] = useState<{ row: DunningCase; action: "recover" | "cancel" } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onConfirm = async (reason: string) => {
    if (!pending) return;
    setError(null);
    try {
      await act.mutateAsync({ id: pending.row.id, action: pending.action, reason });
      toast("Case updated");
      setPending(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Something went wrong.");
    }
  };

  const columns = [
    {
      key: "tenant",
      header: "Customer",
      render: (row: DunningCase) =>
        row.tenant_name ? (
          <Link className="lf-admin-tenant-link" to={`/admin/tenants/${row.tenant_id}`}>
            {row.tenant_name}
          </Link>
        ) : (
          <Text size="sm" tone="tertiary">deleted workspace</Text>
        ),
    },
    {
      key: "amount",
      header: "Outstanding",
      align: "right" as const,
      render: (row: DunningCase) => money(row.amount_minor, row.currency),
    },
    {
      key: "status",
      header: "Status",
      render: (row: DunningCase) => <Badge tone={tone(row.status)}>{humanize(row.status)}</Badge>,
    },
    { key: "attempts", header: "Attempts", align: "right" as const, render: (row: DunningCase) => String(row.attempts_made) },
    {
      key: "next",
      header: "Next step",
      render: (row: DunningCase) => moment(row.next_attempt_at),
    },
    {
      key: "suspend",
      header: "Suspends",
      hideMobile: true,
      render: (row: DunningCase) => day(row.suspend_at),
    },
    {
      key: "failure",
      header: "Last failure",
      hideMobile: true,
      render: (row: DunningCase) => humanize(row.last_failure_reason),
    },
    {
      key: "actions",
      header: "",
      render: (row: DunningCase) =>
        ["open", "suspended"].includes(row.status) ? (
          <div className="lf-inline lf-gap-2">
            <Button size="sm" onClick={() => setPending({ row, action: "recover" })}>
              Mark recovered
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setPending({ row, action: "cancel" })}>
              Close
            </Button>
          </div>
        ) : null,
    },
  ];

  // The stats above the table follow the complete-page rule: a sum over one
  // page of a paginated list is a lie about the rest, so figures render only
  // when the page holds every case the filter matches. Money additionally
  // requires a single currency — this product never sums across currencies,
  // and a console page does not get an exemption from that.
  const loaded = data?.results ?? [];
  const complete = data != null && loaded.length === data.count;
  const currencies = new Set(loaded.map((row) => row.currency));
  const outstanding =
    complete && loaded.length > 0 && currencies.size === 1
      ? loaded.reduce((sum, row) => sum + row.amount_minor, 0)
      : null;

  return (
    <Stack gap={4}>
      <AdminPageHeader
        title="Payment recovery"
        description="Accounts whose payment failed, on their way to suspension unless the money arrives. Marking a case recovered records that it was settled outside the retry schedule."
        meta={data ? `${data.count} case${data.count === 1 ? "" : "s"}` : undefined}
      />

      {complete && loaded.length > 0 && (
        <Card prominence="quiet">
          <FigureRow>
            <Figure label="Cases in this view" value={String(data!.count)} size="secondary" />
            {outstanding !== null && (
              <Figure
                label="Outstanding"
                amountMinor={outstanding}
                currency={loaded[0].currency}
                neutral
                size="secondary"
              />
            )}
            <Figure
              label="Attempts made"
              value={String(loaded.reduce((sum, row) => sum + row.attempts_made, 0))}
              size="secondary"
            />
          </FigureRow>
        </Card>
      )}

      <div className="lf-admin-toolbar">
        <Select
          label="Status"
          value={status}
          options={[
            { value: "", label: "All" },
            { value: "open", label: "Open" },
            { value: "suspended", label: "Suspended" },
            { value: "recovered", label: "Recovered" },
            { value: "abandoned", label: "Abandoned" },
          ]}
          onChange={(event) => setStatus(event.target.value)}
        />
      </div>
      {isLoading && !data ? (
        <LoadingBlock />
      ) : data?.results.length ? (
        <Table columns={columns} rows={data.results} rowKey={(r) => r.id} responsive stickyHeader />
      ) : (
        <Card>
          <EmptyState icon={Inbox} title="Nothing in recovery" body="No accounts are currently past due." />
        </Card>
      )}

      {pending && (
        <ReasonDialog
          open
          title={pending.action === "recover" ? "Mark as recovered" : "Close case"}
          confirmLabel={pending.action === "recover" ? "Mark recovered" : "Close case"}
          pending={act.isPending}
          error={error}
          onClose={() => setPending(null)}
          onConfirm={onConfirm}
          description={
            pending.action === "recover"
              ? "Restores access and cancels the remaining reminder and suspension schedule."
              : "Stops all further recovery steps without restoring access."
          }
        />
      )}
    </Stack>
  );
}

// ==================================================================== coupons
export function AdminCouponsPage() {
  const { data: staff } = usePlatformMe();
  const can = useCapability(staff);
  const { data, isLoading } = useCoupons();
  const create = useCreateCoupon();
  const deactivate = useDeactivateCoupon();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    code: "",
    name: "",
    kind: "percent",
    value: "20",
    currency: "",
    duration: "once",
  });

  const submit = async () => {
    setError(null);
    try {
      await create.mutateAsync({
        code: form.code,
        name: form.name,
        kind: form.kind,
        // Percentages are basis points on the wire; the form takes whole
        // percent because nobody thinks in bps.
        value: form.kind === "percent" ? Number(form.value) * 100 : Math.round(Number(form.value) * 100),
        currency: form.kind === "fixed" ? form.currency : "",
        duration: form.duration,
      });
      toast("Promotion created");
      setOpen(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Something went wrong.");
    }
  };

  const columns = [
    { key: "code", header: "Code", render: (row: Coupon) => <code>{row.code}</code> },
    { key: "name", header: "Name", render: (row: Coupon) => row.name },
    {
      key: "value",
      header: "Discount",
      render: (row: Coupon) =>
        row.kind === "percent"
          ? `${row.value / 100}%`
          : row.kind === "fixed"
            ? money(row.value, row.currency || "USD")
            : `${row.value} ${row.kind === "free_months" ? "months" : "days"}`,
    },
    { key: "duration", header: "Duration", hideMobile: true, render: (row: Coupon) => row.duration },
    {
      key: "redemptions",
      header: "Used",
      align: "right" as const,
      render: (row: Coupon) => `${row.redemption_count}${row.max_redemptions ? ` / ${row.max_redemptions}` : ""}`,
    },
    {
      key: "state",
      header: "State",
      render: (row: Coupon) =>
        row.is_live ? <Badge tone="success">Live</Badge> : <Badge tone="neutral">Inactive</Badge>,
    },
    {
      key: "actions",
      header: "",
      render: (row: Coupon) =>
        row.is_active && can("coupon.write") ? (
          <Button size="sm" variant="ghost" onClick={() => deactivate.mutate(row.id)}>
            End
          </Button>
        ) : null,
    },
  ];

  // Complete-page rule, as on Recovery: redemption totals are only shown when
  // this page holds every promotion, because a total computed from one page of
  // a paginated list quietly misdescribes the campaign.
  const loaded = data?.results ?? [];
  const complete = data != null && loaded.length === data.count;
  const live = loaded.filter((row) => row.is_live).length;
  const redemptions = loaded.reduce((sum, row) => sum + row.redemption_count, 0);

  return (
    <Stack gap={4}>
      <AdminPageHeader
        title="Promotions"
        description="Discount codes customers redeem at checkout. Ending one stops new redemptions; discounts already granted run their course."
        meta={data ? `${data.count} code${data.count === 1 ? "" : "s"}` : undefined}
        actions={can("coupon.write") && <Button onClick={() => setOpen(true)}>New promotion</Button>}
      />

      {complete && loaded.length > 0 && (
        <Card prominence="quiet">
          <FigureRow>
            <Figure label="Live" value={String(live)} size="secondary" />
            <Figure label="Ended" value={String(loaded.length - live)} size="secondary" />
            <Figure
              label="Redemptions"
              value={String(redemptions)}
              size="secondary"
              hint="Across every code"
            />
          </FigureRow>
        </Card>
      )}

      {isLoading && !data ? (
        <LoadingBlock />
      ) : data?.results.length ? (
        <Table columns={columns} rows={data.results} rowKey={(r) => r.id} responsive stickyHeader />
      ) : (
        <Card>
          <EmptyState icon={Inbox} title="No promotions" body="Create one to start a campaign." />
        </Card>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="New promotion">
        <Stack gap={3}>
          <Input
            label="Code"
            value={form.code}
            hint="Customers type this; it is stored uppercase."
            onChange={(e) => setForm({ ...form, code: e.target.value })}
          />
          <Input label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Select
            label="Type"
            value={form.kind}
            options={[
              { value: "percent", label: "Percentage off" },
              { value: "fixed", label: "Fixed amount off" },
              { value: "free_months", label: "Free months" },
              { value: "trial_extension", label: "Trial extension (days)" },
            ]}
            onChange={(e) => setForm({ ...form, kind: e.target.value })}
          />
          <Input
            label={form.kind === "percent" ? "Percent off" : "Value"}
            type="number"
            value={form.value}
            onChange={(e) => setForm({ ...form, value: e.target.value })}
          />
          {form.kind === "fixed" && (
            <Input
              label="Currency"
              value={form.currency}
              hint="A fixed discount is currency-bound and is never converted."
              onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
            />
          )}
          <Select
            label="Duration"
            value={form.duration}
            options={[
              { value: "once", label: "Once" },
              { value: "repeating", label: "Repeating" },
              { value: "forever", label: "Forever" },
            ]}
            onChange={(e) => setForm({ ...form, duration: e.target.value })}
          />
          {error && <Banner tone="danger">{error}</Banner>}
          <div className="lf-admin-dialog-actions">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={submit} disabled={create.isPending || !form.code || !form.name}>
              Create
            </Button>
          </div>
        </Stack>
      </Modal>
    </Stack>
  );
}

// ===================================================================== health
/** Whether anything is watching this deployment, and which half.
 *
 * Surfaced on its own rather than left as one tile among the probes, because
 * the two layers fail differently and an operator needs to know which one they
 * are missing:
 *
 *   on-host alerting  tells you *why* something broke, with diagnosis attached
 *                     — and dies with the host it runs on.
 *   heartbeat         a dead-man's switch: the monitor pings an external
 *                     service after each successful probe, and silence raises
 *                     the alarm. The only layer that survives the host dying.
 *
 * "Not configured" is shown neutral, never red. It is a gap to close, not a
 * live incident, and an amber panel on every fresh install teaches people to
 * ignore the colour that matters.
 */
function MonitoringCard({ snapshot }: { snapshot: HealthSnapshot }) {
  const component = snapshot.components.find((c) => c.name === "monitoring");
  if (!component) return null;

  const channels = (component.channels ?? {}) as Record<string, boolean>;
  const layers = [
    {
      key: "on-host alerting",
      on: Boolean(channels.webhook || channels.email),
      says: "Tells you why — an alert carrying the diagnosis. Cannot report its own host dying.",
    },
    {
      key: "external heartbeat",
      on: Boolean(channels.heartbeat),
      says: "Tells you at all — silence from the monitor raises the alarm. Survives the host.",
    },
  ];

  return (
    <Card title="Monitoring" ruledHeader>
      <ul className="lf-admin-integrations">
        {layers.map((layer) => (
          <li key={layer.key}>
            <span>
              {layer.key}
              <Text size="xs" tone="tertiary">
                {layer.says}
              </Text>
            </span>
            <Badge tone={layer.on ? "success" : "neutral"}>
              {layer.on ? "configured" : "not configured"}
            </Badge>
          </li>
        ))}
      </ul>
      {typeof component.detail === "string" && (
        <Text size="xs" tone="tertiary">
          {component.detail}
        </Text>
      )}
      <Text size="xs" tone="tertiary">
        Both are set in the server's <code>.env</code> — see deploy/README.md. A deployment with
        neither looks exactly like one that has simply had no incidents.
      </Text>
    </Card>
  );
}


export function AdminHealthPage() {
  const { data, isLoading } = useHealth();
  const { data: alerts } = usePlatformNotifications({ open: "true" });
  const ack = useAcknowledgeNotification();

  if (isLoading && !data) return <LoadingBlock label="Probing systems…" />;
  if (!data) return <EmptyState icon={Inbox} title="Unavailable" body="Could not read system health." />;

  return (
    <Stack gap={4}>
      <AdminPageHeader
        title="System"
        description="Live probes, run when this page loads — not a status page cache. A component down here is down right now."
        meta={<Badge tone={tone(data.status)}>{data.status}</Badge>}
      />

      <Grid cols={4} gap={3}>
        {data.components.map((component) => (
          <Card key={component.name} prominence="quiet">
            <Stack gap={1}>
              <div className="lf-admin-kv">
                <strong>{component.name}</strong>
                <Badge tone={tone(component.status)}>{component.status}</Badge>
              </div>
              <Text size="xs" tone="tertiary">
                {component.latency_ms} ms
                {typeof component.detail === "string" ? ` · ${component.detail}` : ""}
              </Text>
            </Stack>
          </Card>
        ))}
      </Grid>

      <MonitoringCard snapshot={data} />

      <Card title="Integrations" ruledHeader>
        <ul className="lf-admin-integrations">
          {data.integrations.map((integration) => (
            <li key={integration.name}>
              <span>{integration.name}</span>
              <Badge tone={integration.status === "unknown" ? "neutral" : tone(integration.status)}>
                {integration.status === "unknown" ? "not configured" : integration.status}
              </Badge>
            </li>
          ))}
        </ul>
        <Text size="xs" tone="tertiary">
          An unconfigured optional integration is shown as neutral, not as an outage.
        </Text>
        {/* Reporting "not configured" without saying where to configure it
            leaves the reader to guess. Payment keys, the AI provider and SMTP
            all live one click away. */}
        <Link to="/admin/settings" className="lf-admin-link">
          Configure integrations →
        </Link>
      </Card>

      <Card title="Open alerts" ruledHeader>
        {alerts?.results.length ? (
          <ul className="lf-admin-alert-list">
            {alerts.results.map((alert) => (
              <li key={alert.id}>
                <div>
                  <Badge tone={tone(alert.severity)}>{alert.severity}</Badge>
                  <strong>{alert.title}</strong>
                  <Text size="xs" tone="tertiary">
                    {moment(alert.created_at)}
                  </Text>
                </div>
                <Button size="sm" variant="ghost" onClick={() => ack.mutate(alert.id)}>
                  Acknowledge
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <Text size="sm" tone="tertiary">
            {/* "Nothing needs attention" was printed directly under a queues
                check reading "down", which is a screen contradicting itself.
                These are raised alerts, not live probe results — saying which
                is true resolves it without hiding either. */}
            No alerts have been raised. Component checks above report live
            status separately.
          </Text>
        )}
      </Card>
    </Stack>
  );
}

// ====================================================================== audit
export function AdminAuditPage() {
  const [query, setQuery] = useState("");
  const [module, setModule] = useState("");
  const { data, isLoading } = useAuditLog({ q: query, module });

  const columns = [
    {
      key: "when",
      header: "When",
      render: (row: AuditRow) => moment(row.created_at),
    },
    { key: "actor", header: "Who", render: (row: AuditRow) => row.actor_email || "system" },
    { key: "action", header: "Action", render: (row: AuditRow) => <code>{row.action}</code> },
    { key: "reason", header: "Why", render: (row: AuditRow) => row.reason || "—" },
    {
      key: "changes",
      header: "Changed",
      hideMobile: true,
      render: (row: AuditRow) =>
        Object.keys(row.changes ?? {}).length ? (
          <ul className="lf-admin-changes">
            {Object.entries(row.changes).map(([field, [before, after]]) => (
              <li key={field}>
                <code>{field}</code>: {String(before)} → {String(after)}
              </li>
            ))}
          </ul>
        ) : (
          "—"
        ),
    },
    { key: "ip", header: "IP", hideMobile: true, render: (row: AuditRow) => row.ip_address || "—" },
  ];

  return (
    <Stack gap={4}>
      <AdminPageHeader
        title="Audit log"
        description="Append-only. Entries cannot be edited or removed, including by a database administrator."
        meta={data ? `${data.count} entr${data.count === 1 ? "y" : "ies"}` : undefined}
      />
      <div className="lf-admin-toolbar">
        <div className="lf-admin-toolbar-search">
          <Input
            label="Search"
            placeholder="Person, action, or reason"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
          <Select
            label="Module"
            value={module}
            options={[
              { value: "", label: "All" },
              { value: "tenants", label: "Customers" },
              { value: "billing", label: "Billing" },
              { value: "impersonation", label: "Impersonation" },
              { value: "staff", label: "Access" },
            ]}
            onChange={(event) => setModule(event.target.value)}
          />
      </div>
      {isLoading && !data ? (
        <LoadingBlock />
      ) : data?.results.length ? (
        <Table columns={columns} rows={data.results} rowKey={(r) => r.id} responsive stickyHeader />
      ) : (
        <Card>
          <EmptyState icon={Inbox} title="No entries" body="Nothing matches this filter." />
        </Card>
      )}
    </Stack>
  );
}

// ====================================================================== staff
export function AdminStaffPage() {
  const { data: me } = usePlatformMe();
  const can = useCapability(me);
  const { data, isLoading } = usePlatformStaff();
  const appoint = useAppointStaff();
  const revoke = useRevokeStaff();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("read_only_auditor");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    try {
      await appoint.mutateAsync({ email, role });
      toast(`${"Appointed"} — ${"The grant was recorded in the audit log."}`, { tone: "success" });
      setOpen(false);
      setEmail("");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Something went wrong.");
    }
  };

  const columns = [
    { key: "email", header: "Person", render: (row: PlatformStaff) => row.email },
    {
      key: "role",
      header: "Role",
      render: (row: PlatformStaff) => <Badge tone="neutral">{row.role.replace(/_/g, " ")}</Badge>,
    },
    {
      key: "mfa",
      header: "2FA",
      render: (row: PlatformStaff) =>
        row.require_mfa ? <Badge tone="success">Required</Badge> : <Badge tone="warning">Waived</Badge>,
    },
    {
      key: "caps",
      header: "Capabilities",
      align: "right" as const,
      hideMobile: true,
      render: (row: PlatformStaff) => String(row.capabilities.length),
    },
    {
      key: "seen",
      header: "Last seen",
      hideMobile: true,
      render: (row: PlatformStaff) =>
        row.last_seen_at ? moment(row.last_seen_at) : "Never",
    },
    {
      key: "state",
      header: "State",
      render: (row: PlatformStaff) =>
        row.is_active ? <Badge tone="success">Active</Badge> : <Badge tone="danger">Revoked</Badge>,
    },
    {
      key: "actions",
      header: "",
      render: (row: PlatformStaff) =>
        row.is_active && can("staff.manage") && row.id !== me?.id ? (
          <Button size="sm" variant="ghost" onClick={() => revoke.mutate(row.id)}>
            Revoke
          </Button>
        ) : null,
    },
  ];

  return (
    <Stack gap={4}>
      <AdminPageHeader
        title="Platform access"
        description="Who can act on customer accounts, and as what. You cannot grant a capability you don't hold yourself, and you cannot change your own role."
        meta={data ? `${data.count} ${data.count === 1 ? "person" : "people"}` : undefined}
        actions={can("staff.manage") && <Button onClick={() => setOpen(true)}>Appoint</Button>}
      />

      {isLoading && !data ? (
        <LoadingBlock />
      ) : data?.results.length ? (
        <Table columns={columns} rows={data.results} rowKey={(r) => r.id} responsive stickyHeader />
      ) : (
        <Card>
          <EmptyState icon={Inbox} title="No platform staff" body="Nobody has been appointed yet." />
        </Card>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="Appoint platform staff">
        <Stack gap={3}>
          <Input
            label="Email"
            type="email"
            value={email}
            hint="The person must already have a LedgerFlow account."
            onChange={(event) => setEmail(event.target.value)}
          />
          <Select
            label="Role"
            value={role}
            options={[
              { value: "platform_owner", label: "Platform Owner" },
              { value: "platform_administrator", label: "Platform Administrator" },
              { value: "billing_administrator", label: "Billing Administrator" },
              { value: "finance", label: "Finance" },
              { value: "customer_success", label: "Customer Success" },
              { value: "technical_support", label: "Technical Support" },
              { value: "read_only_auditor", label: "Read Only Auditor" },
            ]}
            onChange={(event) => setRole(event.target.value)}
          />
          {error && <Banner tone="danger">{error}</Banner>}
          <div className="lf-admin-dialog-actions">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={submit} disabled={appoint.isPending || !email}>
              Appoint
            </Button>
          </div>
        </Stack>
      </Modal>
    </Stack>
  );
}
