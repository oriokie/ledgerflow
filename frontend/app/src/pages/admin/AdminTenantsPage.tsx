import { ArrowLeft, Inbox } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import type { ImpersonationGrant, TenantRow } from "../../api/platform";
import { ApiError } from "../../api/client";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import { ReasonDialog } from "../../components/admin/AdminShell";
import {
  useEndImpersonation,
  useImpersonations,
  useInvoices,
  useCapability,
  usePlatformMe,
  usePlatformPlans,
  useStartImpersonation,
  useTenant,
  useTenantAction,
  useTenants,
} from "../../hooks/usePlatform";
import { countryName } from "../../lib/countries";
import { majorToMinor } from "../../lib/money";
import {
  Banner,
  Eyebrow,
  Badge,
  Button,
  Card,
  EmptyState,
  Figure,
  FigureRow,
  Grid,
  Heading,
  Input,
  LoadingBlock,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  useToast,
} from "../../ui";
import type { SortDirection } from "../../ui";
import { AdminPagination } from "./AdminPagination";
import { bytes, day, humanize, initials, money, moment, tone } from "./format";

export function AdminTenantsPage() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [planId, setPlanId] = useState("");
  const [country, setCountry] = useState("");
  const [subscriptionStatus, setSubscriptionStatus] = useState("");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<{ key: string; direction: SortDirection }>({
    key: "created_at",
    direction: "desc",
  });
  const { data, isLoading } = useTenants({
    q: query,
    status,
    plan_id: planId,
    country,
    subscription_status: subscriptionStatus,
    order_by: `${sort.direction === "desc" ? "-" : ""}${sort.key}`,
    page,
  });
  const { data: plans } = usePlatformPlans();

  // No dedicated facet endpoint backs the country filter, so its options are
  // read off the page already in hand — same data, no extra request. The
  // currently-selected country is always kept in the list even once
  // filtering narrows `data.results` down to that one country, so choosing a
  // country never makes its own option disappear.
  const countryOptions = Array.from(
    new Set([...(data?.results.map((row) => row.country).filter(Boolean) ?? []), country].filter(Boolean)),
  ).sort() as string[];

  const handleSort = (key: string) => {
    setSort((prev) =>
      prev.key === key ? { key, direction: prev.direction === "asc" ? "desc" : "asc" } : { key, direction: "asc" },
    );
    setPage(1);
  };

  const columns = [
    {
      key: "name",
      header: "Workspace",
      sortable: true,
      render: (row: TenantRow) => (
        <div className="lf-admin-tenant-cell">
          <span className="lf-admin-tenant-mark" aria-hidden>
            {initials(row.name)}
          </span>
          <Stack gap={1}>
            <Link to={`/admin/tenants/${row.id}`} className="lf-admin-link">
              {row.name}
            </Link>
            <Text size="xs" tone="tertiary">
              {row.owner_email || row.billing_email || "No owner on record"}
            </Text>
          </Stack>
        </div>
      ),
    },
    {
      key: "plan",
      header: "Plan",
      render: (row: TenantRow) => (
        <Stack gap={1}>
          <span>
            {row.plan_name || "—"}
            {" · "}
            <span className="lf-admin-code">{row.currency}</span>
            {row.billing_currency && row.billing_currency !== row.currency
              ? ` · billed ${row.billing_currency}`
              : ""}
          </span>
          {row.subscription_status ? (
            <Badge tone={tone(row.subscription_status)}>
              {row.subscription_status.replace(/_/g, " ")}
            </Badge>
          ) : null}
          {row.subscription_status === "trialing" && row.trial_ends_at && (
            <Text size="xs" tone="tertiary">
              Trial until {day(row.trial_ends_at)}
            </Text>
          )}
        </Stack>
      ),
    },
    {
      key: "mrr",
      header: "MRR",
      align: "right" as const,
      render: (row: TenantRow) =>
        row.subscription_status ? money(row.mrr_minor, row.billing_currency || row.currency) : "—",
    },
    {
      key: "members",
      header: "Seats",
      align: "right" as const,
      hideMobile: true,
      sortable: true,
      render: (row: TenantRow) => String(row.member_count),
    },
    {
      key: "country",
      header: "Country",
      hideMobile: true,
      render: (row: TenantRow) => countryName(row.country) || "—",
    },
    {
      key: "state",
      header: "State",
      render: (row: TenantRow) =>
        row.is_active ? <Badge tone="success">Active</Badge> : <Badge tone="danger">Suspended</Badge>,
    },
    {
      key: "last_activity",
      header: "Last seen",
      hideMobile: true,
      sortable: true,
      render: (row: TenantRow) => day(row.last_activity),
    },
    {
      key: "created_at",
      header: "Joined",
      hideMobile: true,
      sortable: true,
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
        <Select
          label="Plan"
          value={planId}
          options={[
            { value: "", label: "All" },
            ...(plans ?? []).map((plan) => ({ value: plan.id, label: plan.name })),
          ]}
          onChange={(event) => {
            setPlanId(event.target.value);
            setPage(1);
          }}
        />
        <Select
          label="Billing"
          value={subscriptionStatus}
          options={[
            { value: "", label: "Any status" },
            { value: "trialing", label: "Trialing" },
            { value: "active", label: "Paying" },
            { value: "past_due", label: "Past due" },
            { value: "canceled", label: "Canceled" },
          ]}
          onChange={(event) => {
            setSubscriptionStatus(event.target.value);
            setPage(1);
          }}
        />
        <Select
          label="Country"
          value={country}
          options={[
            { value: "", label: "All" },
            ...countryOptions.map((code) => ({ value: code, label: countryName(code) || code })),
          ]}
          onChange={(event) => {
            setCountry(event.target.value);
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
            sort={sort}
            onSort={handleSort}
          />
          <AdminPagination
            page={page}
            onPageChange={setPage}
            hasPrevious={Boolean(data.previous)}
            hasNext={Boolean(data.next)}
            label={`${data.count} workspace${data.count === 1 ? "" : "s"}`}
          />
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
  | { kind: "resume-subscription" }
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
  "resume-subscription": { title: "Resume subscription", confirm: "Resume" },
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
  const { data: sessions } = useImpersonations({ active: "true" });
  const endSession = useEndImpersonation();
  const toast = useToast();

  const [pending, setPending] = useState<PendingAction>(null);
  const [planId, setPlanId] = useState("");
  const [days, setDays] = useState("14");
  const [months, setMonths] = useState("1");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [reveal, setReveal] = useState<ImpersonationGrant | null>(null);
  const [ending, setEnding] = useState<ImpersonationGrant | null>(null);
  const [endError, setEndError] = useState<string | null>(null);

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
        // The raw token is returned once and is never stored. The toast used
        // to claim a session had started while discarding the only credential
        // that could actually open it.
        close();
        setReveal(grant);
        return;
      } else {
        const body: Record<string, unknown> = { reason };
        if (pending.kind === "extend-trial") body.days = Number(days);
        if (pending.kind === "change-plan") body.plan_id = planId;
        if (pending.kind === "complimentary") {
          body.plan_id = planId;
          body.months = Number(months);
        }
        if (pending.kind === "credit") {
          const billed = tenant.billing_currency || tenant.subscription?.currency || tenant.currency;
          body.amount_minor = majorToMinor(Number(amount), billed);
          body.currency = billed;
        }
        await action.mutateAsync({ action: pending.kind, body });
        toast("The action was recorded in the audit log.", { tone: "success" });
      }
      close();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Something went wrong.");
    }
  };

  const copy = pending ? ACTION_COPY[pending.kind] : null;
  const sub = tenant.subscription;
  const billedIn = tenant.billing_currency || sub?.currency || "";
  const currenciesDiverge = Boolean(billedIn && billedIn !== tenant.currency);
  const liveSessions = (sessions?.results ?? []).filter(
    (grant) => grant.tenant_id === tenantId && grant.status === "active",
  );
  const subscriptionPendingCancel = Boolean(sub?.cancel_at_period_end || sub?.status === "canceled");

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
            <Badge tone="neutral">{humanize(tenant.type)}</Badge>
          </div>
          <Text size="sm" tone="secondary">
            {countryName(tenant.country) || "Country not stated"} · {tenant.timezone}
            {tenant.billing_email ? ` · ${tenant.billing_email}` : ""}
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

      {currenciesDiverge && (
        <Banner tone="warning">
          Books are kept in {tenant.currency}. The subscription is billed in {billedIn}. MRR, invoices
          and credits use {billedIn}.
        </Banner>
      )}

      <Card>
        <FigureRow lead>
          {sub ? (
            <Figure
              label="MRR"
              size="hero"
              amountMinor={sub.mrr_minor}
              currency={billedIn || tenant.currency}
              neutral
              hint={`${sub.plan_name} · ${sub.interval}`}
            />
          ) : (
            <Figure label="MRR" size="hero" value="—" hint="No subscription" />
          )}
          <Figure label="Seats" value={String(tenant.usage.member_count)} />
          <Figure label="Transactions" value={tenant.usage.transaction_count.toLocaleString()} />
          <Figure label="Storage" value={bytes(tenant.usage.storage_bytes)} />
        </FigureRow>
      </Card>

      <Grid cols={2} gap={3}>
        <Card title="Workspace">
          <Stack gap={2}>
            <div className="lf-admin-kv">
              <span>Books</span>
              <strong className="lf-admin-code">{tenant.currency}</strong>
            </div>
            <div className="lf-admin-kv">
              <span>Billed in</span>
              <strong className="lf-admin-code">{billedIn || "—"}</strong>
            </div>
            <div className="lf-admin-kv">
              <span>Country</span>
              <span>{countryName(tenant.country) || "—"}</span>
            </div>
            <div className="lf-admin-kv">
              <span>Locale</span>
              <span>{tenant.locale || "—"}</span>
            </div>
            <div className="lf-admin-kv">
              <span>Timezone</span>
              <span>{tenant.timezone}</span>
            </div>
            <div className="lf-admin-kv">
              <span>Joined</span>
              <span>{day(tenant.created_at)}</span>
            </div>
          </Stack>
        </Card>

        <Card title="Subscription">
          {sub ? (
            <Stack gap={2}>
              <div className="lf-admin-kv">
                <span>Plan</span>
                <strong>{sub.plan_name}</strong>
              </div>
              <div className="lf-admin-kv">
                <span>Status</span>
                <Badge tone={tone(sub.status)}>{sub.status.replace(/_/g, " ")}</Badge>
              </div>
              <div className="lf-admin-kv">
                <span>Price</span>
                <strong>{money(sub.price_minor, sub.currency)}</strong>
              </div>
              <div className="lf-admin-kv">
                <span>Provider</span>
                <span>{humanize(sub.provider)}</span>
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
      </Grid>

      <Grid cols={2} gap={3}>
        <Card title="Usage">
          <Stack gap={2}>
            <div className="lf-admin-kv">
              <span>Accounts</span>
              <strong>{tenant.usage.account_count}</strong>
            </div>
            <div className="lf-admin-kv">
              <span>Transactions</span>
              <strong>{tenant.usage.transaction_count.toLocaleString()}</strong>
            </div>
            <div className="lf-admin-kv">
              <span>Attachments</span>
              <strong>{tenant.usage.attachment_count}</strong>
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
                    {member.last_login_at
                      ? ` · last in ${day(member.last_login_at)}`
                      : " · never signed in"}
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
                    <Badge tone={tone(invoice.status)}>{humanize(invoice.status)}</Badge>
                  </td>
                  <td className="lf-admin-mini-amount">{money(invoice.total_minor, invoice.currency)}</td>
                  <td>{day(invoice.issue_date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {can("tenant.impersonate") && liveSessions.length > 0 && (
        <Card title="Open support sessions" ruledHeader>
          <Text size="sm" tone="secondary">
            Live grants against this workspace. Ending one takes effect on the next request.
          </Text>
          <ul className="lf-admin-session-list">
            {liveSessions.map((grant) => (
              <li key={grant.id}>
                <div>
                  <strong>{grant.read_only ? "Read-only" : "Read-write"}</strong>
                  <Text size="xs" tone="tertiary">
                    {grant.staff_email} · expires {moment(grant.expires_at)} · {grant.request_count}{" "}
                    request{grant.request_count === 1 ? "" : "s"}
                  </Text>
                </div>
                <Button size="sm" variant="secondary" onClick={() => setEnding(grant)}>
                  End session
                </Button>
              </li>
            ))}
          </ul>
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
              {can("subscription.write") &&
                (subscriptionPendingCancel ? (
                  <Button variant="secondary" onClick={() => setPending({ kind: "resume-subscription" })}>
                    Resume subscription
                  </Button>
                ) : (
                  <Button
                    variant="secondary"
                    onClick={() => setPending({ kind: "cancel-subscription" })}
                  >
                    Cancel subscription
                  </Button>
                ))}
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
              label={`Amount (${tenant.billing_currency || tenant.subscription?.currency || tenant.currency})`}
              type="number"
              min={0}
              step="0.01"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          )}
        </ReasonDialog>
      )}

      {reveal && (
        <ImpersonationTokenDialog grant={reveal} onClose={() => setReveal(null)} />
      )}

      {ending && (
        <ReasonDialog
          open
          title="End support session"
          confirmLabel="End session"
          destructive
          pending={endSession.isPending}
          error={endError}
          onClose={() => {
            setEnding(null);
            setEndError(null);
          }}
          onConfirm={async (reason) => {
            setEndError(null);
            try {
              await endSession.mutateAsync({ id: ending.id, reason });
              toast("Session ended", { tone: "success" });
              setEnding(null);
            } catch (err) {
              setEndError(err instanceof ApiError ? err.detail : "Couldn't end the session.");
            }
          }}
          description="The grant stops working on the next request. This is recorded in the audit log."
        />
      )}
    </Stack>
  );
}

function ImpersonationTokenDialog({
  grant,
  onClose,
}: {
  grant: ImpersonationGrant;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const token = grant.token ?? "";

  const copyToken = async () => {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Session token — copy it now"
      description="This is shown once and is never stored. Without it the grant you just created cannot be used."
      footer={
        <Button variant="primary" onClick={onClose}>
          I've copied it
        </Button>
      }
    >
      <Stack gap={3}>
        <Text size="sm" tone="secondary">
          Read-only, expires {new Date(grant.expires_at).toLocaleString()}. Every request made with
          this token is counted and audited.
        </Text>
        <div className="lf-admin-token">
          <code>{token}</code>
          <Button size="sm" variant="secondary" onClick={() => void copyToken()}>
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </Stack>
    </Modal>
  );
}
