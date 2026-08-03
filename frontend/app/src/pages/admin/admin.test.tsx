import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlatformStaff } from "../../api/platform";
import { bytes, money, percent } from "./format";

/**
 * Capability gating is the behaviour under test.
 *
 * The client hides controls the operator cannot use — a courtesy, since the
 * API enforces the same capability independently — so these tests assert that
 * the *right* things disappear for the *right* role. Getting this wrong is not
 * a security hole, but it does mean showing someone a button that will 403,
 * which is a worse experience than not showing it.
 */
const staffState: { value: PlatformStaff | null; isLoading: boolean; isError: boolean } = {
  value: null,
  isLoading: false,
  isError: false,
};

function makeStaff(role: string, capabilities: string[]): PlatformStaff {
  return {
    id: "staff-1",
    user_id: "user-1",
    email: "ops@example.com",
    name: "Ops Person",
    role: role as PlatformStaff["role"],
    is_active: true,
    require_mfa: true,
    allowed_ips: [],
    extra_capabilities: [],
    denied_capabilities: [],
    capabilities,
    last_seen_at: null,
    note: "",
    created_at: "2026-01-01T00:00:00Z",
  };
}

const tenantDetail = {
  id: "t1",
  name: "The Otieno Household",
  type: "household",
  is_active: true,
  ai_enabled: true,
  country: "KE",
  timezone: "Africa/Nairobi",
  locale: "en-KE",
  currency: "KES",
  billing_email: "owner@example.com",
  created_at: "2026-01-01T00:00:00Z",
  subscription: {
    id: "s1",
    plan_id: "p1",
    plan_name: "Plus",
    plan_tier: "plus",
    interval: "monthly",
    price_minor: 90000,
    currency: "KES",
    status: "active",
    trial_end: null,
    current_period_start: null,
    current_period_end: null,
    cancel_at_period_end: false,
    canceled_at: null,
    provider: "mpesa",
    mrr_minor: 90000,
  },
  members: [
    {
      id: "m1",
      user_id: "u1",
      email: "owner@example.com",
      name: "Amina",
      role: "owner",
      last_login_at: null,
      is_active: true,
      joined_at: "2026-01-01T00:00:00Z",
    },
  ],
  usage: {
    captured_at: "2026-07-01T00:00:00Z",
    member_count: 1,
    account_count: 4,
    transaction_count: 812,
    attachment_count: 12,
    storage_bytes: 5_242_880,
  },
};

const invoiceRow = {
  id: "inv-1",
  number: "INV-2026-000001",
  tenant_id: "t1",
  status: "pending",
  currency: "USD",
  issue_date: "2026-07-01",
  due_date: "2026-07-15",
  paid_at: null,
  subtotal_minor: 900,
  discount_minor: 0,
  credit_minor: 0,
  tax_minor: 0,
  tax_label: "",
  total_minor: 900,
  amount_paid_minor: 0,
  amount_due_minor: 900,
  billing_name: "Amina",
  billing_email: "amina@example.test",
  billing_country: "KE",
  line_items: [],
};
const invoicesState: { value: (typeof invoiceRow)[] } = { value: [] };
const downloadMutate = vi.fn().mockResolvedValue(undefined);
const sendMutate = vi.fn().mockResolvedValue({ queued: true, to: "amina@example.test" });

const tenantActionMutate = vi.fn().mockResolvedValue(tenantDetail);
const impersonateMutate = vi.fn().mockResolvedValue({
  id: "g1",
  expires_at: "2026-07-26T12:30:00Z",
  token: "raw-token-shown-once",
});

// The rail now carries a sign-out, so the shell needs an auth context. The
// suite is about navigation and capability filtering, not about sessions.
vi.mock("../../lib/AuthContext", () => ({
  useAuth: () => ({ logout: vi.fn() }),
}));

vi.mock("../../hooks/usePlatform", async () => {
  const actual = await vi.importActual<typeof import("../../hooks/usePlatform")>(
    "../../hooks/usePlatform",
  );
  return {
    ...actual,
    usePlatformMe: () => ({
      data: staffState.value,
      isLoading: staffState.isLoading,
      isError: staffState.isError,
    }),
    useTenant: () => ({ data: tenantDetail, isLoading: false }),
    useTenants: () => ({ data: { count: 0, next: null, previous: null, results: [] }, isLoading: false }),
    usePlatformPlans: () => ({ data: [] }),
    useTenantAction: () => ({ mutateAsync: tenantActionMutate, isPending: false }),
    useStartImpersonation: () => ({ mutateAsync: impersonateMutate, isPending: false }),
    usePlatformNotifications: () => ({ data: { count: 0, results: [] } }),
    useInvoices: () => ({
      data: { count: invoicesState.value.length, next: null, previous: null, results: invoicesState.value },
      isLoading: false,
    }),
    useDownloadInvoice: () => ({ mutateAsync: downloadMutate, mutate: downloadMutate, isPending: false }),
    useSendInvoice: () => ({ mutateAsync: sendMutate, isPending: false }),
  };
});

import { AdminGuard, AdminShell, ReasonDialog } from "../../components/admin/AdminShell";
import { AdminTenantDetailPage } from "./AdminTenantsPage";

function renderAt(ui: React.ReactNode, path = "/admin/tenants/t1") {
  return render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);
}

beforeEach(() => {
  staffState.value = null;
  staffState.isLoading = false;
  staffState.isError = false;
  tenantActionMutate.mockClear();
  impersonateMutate.mockClear();
  downloadMutate.mockClear();
  sendMutate.mockClear();
  invoicesState.value = [];
});

// ================================================================ formatters
describe("formatters", () => {
  it("renders minor units as currency", () => {
    expect(money(123_456, "USD")).toContain("1,235");
  });

  it("distinguishes an absent value from zero", () => {
    // "we could not compute this" and "this is zero" lead to different actions.
    expect(money(null)).toBe("—");
    expect(money(0, "USD")).toContain("0");
    expect(percent(null)).toBe("—");
    expect(percent(0)).toBe("0.0%");
  });

  it("formats byte counts compactly", () => {
    expect(bytes(0)).toBe("0 B");
    expect(bytes(5_242_880)).toBe("5.0 MB");
  });
});

// ===================================================================== guard
describe("AdminGuard", () => {
  it("refuses flatly rather than redirecting", () => {
    // A redirect would confirm /admin exists and that the visitor merely lacks
    // access. A flat refusal tells a prober nothing.
    staffState.isError = true;
    render(
      <MemoryRouter>
        <AdminGuard>
          <p>secret</p>
        </AdminGuard>
      </MemoryRouter>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("lets platform staff through", () => {
    staffState.value = makeStaff("platform_owner", ["tenant.read"]);
    render(
      <MemoryRouter>
        <AdminGuard>
          <p>console</p>
        </AdminGuard>
      </MemoryRouter>,
    );
    expect(screen.getByText("console")).toBeInTheDocument();
  });
});

// =================================================================== the nav
describe("navigation", () => {
  it("shows only the sections the operator can use", () => {
    staffState.value = makeStaff("finance", [
      "platform.dashboard.view",
      "billing.read",
      "audit.read",
    ]);
    renderAt(<AdminShell />, "/admin");

    expect(screen.getByRole("link", { name: /billing/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /audit/i })).toBeInTheDocument();
    // Finance has no staff.read, so the Access tab would only ever 403.
    expect(screen.queryByRole("link", { name: /access/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /customers/i })).not.toBeInTheDocument();
  });
});

// ============================================================ reason dialog
describe("ReasonDialog", () => {
  it("will not submit until a real reason is given", () => {
    const onConfirm = vi.fn();
    render(
      <ReasonDialog
        open
        title="Suspend workspace"
        confirmLabel="Suspend"
        onConfirm={onConfirm}
        onClose={vi.fn()}
      />,
    );

    const confirm = screen.getByRole("button", { name: "Suspend" });
    expect(confirm).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "abc" } });
    expect(confirm).toBeDisabled(); // still under the minimum

    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: "Confirmed chargeback fraud" },
    });
    expect(confirm).toBeEnabled();

    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledWith("Confirmed chargeback fraud");
  });

  it("holds impersonation to a longer explanation", () => {
    render(
      <ReasonDialog
        open
        title="Open customer workspace"
        confirmLabel="Start session"
        minLength={10}
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "support" } });
    expect(screen.getByRole("button", { name: "Start session" })).toBeDisabled();
  });

  it("tells the operator the reason is permanent", () => {
    render(<ReasonDialog open title="Suspend" onConfirm={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText(/recorded permanently in the audit log/i)).toBeInTheDocument();
  });
});

// ============================================================ tenant actions
describe("tenant detail", () => {
  it("offers only the actions the role holds", () => {
    staffState.value = makeStaff("read_only_auditor", ["tenant.read"]);
    renderAt(<AdminTenantDetailPage />);

    expect(screen.getByText("The Otieno Household")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /suspend/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open workspace/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /issue credit/i })).not.toBeInTheDocument();
  });

  it("offers suspension and impersonation to customer success", () => {
    staffState.value = makeStaff("customer_success", [
      "tenant.read",
      "tenant.suspend",
      "tenant.impersonate",
    ]);
    renderAt(<AdminTenantDetailPage />);

    expect(screen.getByRole("button", { name: /suspend/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open workspace/i })).toBeInTheDocument();
  });

  it("sends the reason with the action", async () => {
    staffState.value = makeStaff("platform_owner", ["tenant.read", "tenant.suspend"]);
    renderAt(<AdminTenantDetailPage />);

    fireEvent.click(screen.getByRole("button", { name: /suspend/i }));
    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: "Repeated chargebacks confirmed by the provider" },
    });
    // Scoped to the dialog: the page's own Suspend trigger is still mounted
    // behind it, and an unscoped query matches both.
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Suspend" }));

    await waitFor(() =>
      expect(tenantActionMutate).toHaveBeenCalledWith({
        action: "suspend",
        body: { reason: "Repeated chargebacks confirmed by the provider" },
      }),
    );
  });

  it("warns that impersonation exposes household financial data", () => {
    staffState.value = makeStaff("customer_success", ["tenant.read", "tenant.impersonate"]);
    renderAt(<AdminTenantDetailPage />);

    fireEvent.click(screen.getByRole("button", { name: /open workspace/i }));
    expect(screen.getByText(/financial data/i)).toBeInTheDocument();
    expect(screen.getByText(/read-only/i)).toBeInTheDocument();
  });

  it("starts impersonation read-only by default", async () => {
    staffState.value = makeStaff("customer_success", ["tenant.read", "tenant.impersonate"]);
    renderAt(<AdminTenantDetailPage />);

    fireEvent.click(screen.getByRole("button", { name: /open workspace/i }));
    fireEvent.change(screen.getByLabelText(/reason/i), {
      target: { value: "Customer reports a missing March statement" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start session" }));

    await waitFor(() =>
      expect(impersonateMutate).toHaveBeenCalledWith({
        reason: "Customer reports a missing March statement",
        read_only: true,
      }),
    );
  });

  it("shows usage magnitudes but no financial content", () => {
    staffState.value = makeStaff("platform_owner", ["tenant.read"]);
    renderAt(<AdminTenantDetailPage />);

    // Counts and bytes cross the RLS boundary; balances and transactions do not.
    expect(screen.getByText("812")).toBeInTheDocument();
    expect(screen.getByText("5.0 MB")).toBeInTheDocument();
    expect(screen.queryByText(/net worth/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/balance/i)).not.toBeInTheDocument();
  });
});

// ================================================================== invoices
describe("invoice actions", () => {
  it("offers a PDF download to anyone who can read billing", async () => {
    const { AdminInvoicesPage } = await import("./AdminPages");
    staffState.value = makeStaff("read_only_auditor", ["billing.read"]);
    invoicesState.value = [invoiceRow];

    renderAt(<AdminInvoicesPage />, "/admin/invoices");

    expect(screen.getByRole("button", { name: "PDF" })).toBeInTheDocument();
    // Emailing a customer is a write; reading a document is not.
    expect(screen.queryByRole("button", { name: "Email" })).not.toBeInTheDocument();
  });

  it("offers emailing only with invoice.write", async () => {
    const { AdminInvoicesPage } = await import("./AdminPages");
    staffState.value = makeStaff("finance", ["billing.read", "invoice.write"]);
    invoicesState.value = [invoiceRow];

    renderAt(<AdminInvoicesPage />, "/admin/invoices");

    expect(screen.getByRole("button", { name: "Email" })).toBeInTheDocument();
  });

  it("does not offer to email a draft", async () => {
    const { AdminInvoicesPage } = await import("./AdminPages");
    staffState.value = makeStaff("finance", ["billing.read", "invoice.write"]);
    invoicesState.value = [{ ...invoiceRow, status: "draft" }];

    renderAt(<AdminInvoicesPage />, "/admin/invoices");

    expect(screen.queryByRole("button", { name: "Email" })).not.toBeInTheDocument();
  });

  it("downloads through the authenticated client, not a bare link", async () => {
    const { AdminInvoicesPage } = await import("./AdminPages");
    staffState.value = makeStaff("finance", ["billing.read"]);
    invoicesState.value = [invoiceRow];

    renderAt(<AdminInvoicesPage />, "/admin/invoices");
    fireEvent.click(screen.getByRole("button", { name: "PDF" }));

    // A plain <a href> would 401 — the endpoint needs the Authorization header.
    await waitFor(() =>
      expect(downloadMutate).toHaveBeenCalledWith({ id: "inv-1", number: "INV-2026-000001" }),
    );
  });
});

describe("signing out of the console", () => {
  it("offers a way out of the console at all", () => {
    // "Back to LedgerFlow" is not a sign out — and for a platform account it is
    // a dead end, because the customer app has no workspace to send an operator
    // to and bounces them straight back. Before this an operator who could
    // suspend somebody's account could not end their own session, which on a
    // shared or unattended machine is the whole problem.
    staffState.value = makeStaff("superuser", ["platform.dashboard.view"]);
    renderAt(<AdminShell />, "/admin");
    expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
  });
});
