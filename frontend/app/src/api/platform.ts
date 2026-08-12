/**
 * Platform administration API client.
 *
 * Separate from the tenant API modules for the same reason the backend routes
 * are separate: nothing here sends an `X-Tenant-ID` header. Every call passes
 * `skipTenant`, so an admin request cannot accidentally inherit whichever
 * workspace the operator happened to have open in the customer app.
 */
import { api, getBlob } from "./client";

const BASE = "/platform";
const NO_TENANT = { skipTenant: true } as const;

/** Standard DRF page envelope used by every admin list endpoint. */
export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// ------------------------------------------------------------------- identity
export type PlatformRole =
  | "platform_owner"
  | "platform_administrator"
  | "billing_administrator"
  | "finance"
  | "customer_success"
  | "technical_support"
  | "read_only_auditor";

export interface PlatformStaff {
  id: string;
  user_id: string;
  email: string;
  name: string;
  role: PlatformRole;
  is_active: boolean;
  require_mfa: boolean;
  allowed_ips: string[];
  extra_capabilities: string[];
  denied_capabilities: string[];
  /** Resolved server-side, so the client never reimplements the role mapping. */
  capabilities: string[];
  last_seen_at: string | null;
  note: string;
  created_at: string;
}

export interface CapabilityCatalog {
  capabilities: { capability: string; module: string; roles: string[] }[];
  roles: { value: PlatformRole; label: string }[];
}

// -------------------------------------------------------------------- tenants
export interface TenantRow {
  id: string;
  name: string;
  type: string;
  is_active: boolean;
  country: string;
  timezone: string;
  currency: string;
  locale: string;
  billing_email: string;
  owner_email: string;
  owner_name: string;
  member_count: number;
  plan_name: string;
  plan_id: string | null;
  subscription_status: string;
  trial_ends_at: string | null;
  current_period_end: string | null;
  mrr_minor: number;
  created_at: string;
  last_activity: string | null;
  last_payment_at: string | null;
  storage_bytes: number;
  transaction_count: number;
}

export interface TenantDetail {
  id: string;
  name: string;
  type: string;
  is_active: boolean;
  ai_enabled: boolean;
  country: string;
  timezone: string;
  locale: string;
  currency: string;
  billing_email: string;
  created_at: string;
  subscription: SubscriptionDetail | null;
  members: {
    id: string;
    user_id: string;
    email: string;
    name: string;
    role: string;
    last_login_at: string | null;
    is_active: boolean;
    joined_at: string;
  }[];
  usage: {
    captured_at: string | null;
    member_count: number;
    account_count: number;
    transaction_count: number;
    attachment_count: number;
    storage_bytes: number;
  };
}

export interface SubscriptionDetail {
  id: string;
  plan_id: string;
  plan_name: string;
  plan_tier: string;
  interval: string;
  price_minor: number;
  currency: string;
  status: string;
  trial_end: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  canceled_at: string | null;
  provider: string;
  mrr_minor: number;
}

export interface TenantFilters {
  q?: string;
  status?: string;
  country?: string;
  plan_id?: string;
  subscription_status?: string;
  order_by?: string;
  page?: number;
  page_size?: number;
}

// -------------------------------------------------------------------- billing
export interface Invoice {
  id: string;
  number: string;
  tenant_id: string;
  /** Resolved server-side; "" when the workspace has been deleted. */
  tenant_name: string;
  status: string;
  currency: string;
  issue_date: string;
  due_date: string;
  paid_at: string | null;
  subtotal_minor: number;
  discount_minor: number;
  credit_minor: number;
  tax_minor: number;
  tax_label: string;
  total_minor: number;
  amount_paid_minor: number;
  amount_due_minor: number;
  billing_name: string;
  billing_email: string;
  billing_country: string;
  line_items: {
    description: string;
    quantity: number;
    unit_amount_minor: number;
    amount_minor: number;
    period_start: string | null;
    period_end: string | null;
  }[];
}

export interface Refund {
  id: string;
  tenant_id: string;
  payment_id: string;
  amount_minor: number;
  currency: string;
  reason: string;
  status: string;
  requested_by_email: string;
  approved_by_email: string;
  approved_at: string | null;
  completed_at: string | null;
  decision_note: string;
  provider: string;
  provider_ref: string;
  failure_reason: string;
  created_at: string;
}

export interface PaymentRow {
  id: string;
  tenant_id: string;
  amount_minor: number;
  currency: string;
  status: string;
  provider: string;
  provider_ref: string;
  description: string;
  failure_reason: string;
  created_at: string;
}

export interface Coupon {
  id: string;
  code: string;
  name: string;
  description: string;
  kind: string;
  value: number;
  currency: string;
  duration: string;
  duration_in_months: number | null;
  allowed_countries: string[];
  starts_at: string | null;
  expires_at: string | null;
  max_redemptions: number | null;
  max_redemptions_per_tenant: number;
  redemption_count: number;
  is_active: boolean;
  is_live: boolean;
  created_at: string;
}

export interface DunningCase {
  id: string;
  tenant_id: string;
  /** Resolved server-side; "" when the workspace has been deleted. */
  tenant_name: string;
  subscription_id: string;
  status: string;
  amount_minor: number;
  currency: string;
  opened_at: string;
  grace_ends_at: string | null;
  suspend_at: string | null;
  resolved_at: string | null;
  attempts_made: number;
  last_failure_reason: string;
  next_attempt_at: string | null;
}

export interface PlanFeatureRef {
  key: string;
  label: string;
}

export interface Plan {
  id: string;
  tier: string;
  name: string;
  description: string;
  price_minor: number;
  currency: string;
  interval: string;
  max_members: number;
  max_accounts: number;
  ai_insights: boolean;
  is_active: boolean;
  sort_order: number;
  /** The override list as stored on the row — what an editor round-trips. */
  features: string[];
  /** What the plan actually includes: tier defaults ∪ overrides, labelled. */
  resolved_features: PlanFeatureRef[];
  subscriber_count: number;
}

export interface PlanUpdatePayload {
  name?: string;
  description?: string;
  price_minor?: number;
  max_members?: number;
  max_accounts?: number;
  ai_insights?: boolean;
  features?: string[];
  is_active?: boolean;
  reason: string;
}

export interface CatalogueTier {
  tier: string;
  pitch: string;
  features: string[];
  adds: string[];
  universal: string[];
}

// -------------------------------------------------------------------- other
export interface AuditRow {
  id: string;
  actor_id: string | null;
  actor_email: string;
  actor_role: string;
  action: string;
  module: string;
  target_type: string;
  target_id: string | null;
  tenant_id: string | null;
  changes: Record<string, [unknown, unknown]>;
  reason: string;
  ip_address: string | null;
  user_agent: string;
  request_id: string;
  context: Record<string, unknown>;
  created_at: string;
}

export interface ImpersonationGrant {
  id: string;
  tenant_id: string;
  staff_email: string;
  reason: string;
  read_only: boolean;
  status: string;
  expires_at: string;
  ended_at: string | null;
  request_count: number;
  ip_address: string | null;
  created_at: string;
  /** Present only on the create response; never returned by a listing. */
  token?: string;
}

export interface PlatformNotification {
  id: string;
  category: string;
  severity: "info" | "warning" | "critical";
  title: string;
  body: string;
  tenant_id: string | null;
  data: Record<string, unknown>;
  acknowledged_at: string | null;
  created_at: string;
}

export interface HealthComponent {
  name: string;
  status: "ok" | "degraded" | "down" | "unknown";
  latency_ms: number;
  [key: string]: unknown;
}

export interface HealthSnapshot {
  generated_at: string;
  status: "ok" | "degraded" | "down";
  components: HealthComponent[];
  integrations: { name: string; status: string; configured: boolean }[];
  alerts: { severity: string; category: string; message: string; count: number }[];
}

export interface Dashboard {
  generated_at: string;
  currency: string;
  revenue: {
    mrr_minor: number;
    arr_minor: number;
    paying_customers: number;
    arpa_minor: number;
    currency: string;
    today: { gross_minor: number; refunded_minor: number; net_minor: number };
    month_to_date: { gross_minor: number; refunded_minor: number; net_minor: number };
    lifetime: { gross_minor: number; refunded_minor: number; net_minor: number };
  };
  customers: Record<string, number | null>;
  churn: { rate: number; churned: number; base: number; retention_rate: number | null };
  ltv: { arpa_minor: number; monthly_churn_rate: number; ltv_minor: number | null };
  trials: { conversion_rate: number | null; converted: number; trials_concluded: number };
  payments: { success_rate: number | null; total: number; succeeded: number; failed: number };
  by_plan: RevenueBucket[];
  by_country: RevenueBucket[];
  by_currency: RevenueBucket[];
  by_provider: RevenueBucket[];
}

export interface RevenueBucket {
  key: string;
  mrr_minor: number;
  customers: number;
}

export interface PlatformSetting {
  key: string;
  kind: "string" | "boolean" | "integer" | "json" | "secret";
  group: string;
  label: string;
  help: string;
  env_setting: string | null;
  /** Permitted values, for settings that are a closed set. Empty otherwise —
   * a closed set rendered as a free-text box is how an invalid value gets
   * stored and the only symptom is a screen that quietly stops working. */
  choices: string[];
  /** Which layer supplied the effective value. */
  source: "database" | "environment" | "default";
  overridden: boolean;
  env_configured: boolean;
  /** Always null for secrets — the console can replace one, never read it. */
  value: unknown;
  is_set?: boolean;
  updated_at: string | null;
  updated_by: string | null;
}

export interface SavedView {
  id: string;
  surface: string;
  name: string;
  filters: Record<string, unknown>;
  is_shared: boolean;
  created_at: string;
}

/** Drop empty values so they don't become `?q=&status=` noise in the URL. */
function qs(params: Record<string, unknown> = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export const platformApi = {
  /** Public: the signed-out product needs the illustration style. No auth, and
   * deliberately its own endpoint rather than an exemption on the full
   * settings API — an allowlist of one is easier to keep safe. */
  appearance: () =>
    api.get<{ illustration_style: "clay" | "doodle" }>("/platform/appearance/", {
      skipTenant: true,
    }),

  // Identity
  me: () => api.get<PlatformStaff>(`${BASE}/me/`, NO_TENANT),
  capabilities: () => api.get<CapabilityCatalog>(`${BASE}/capabilities/`, NO_TENANT),

  // Dashboard & analytics
  dashboard: (currency = "USD") =>
    api.get<Dashboard>(`${BASE}/dashboard/${qs({ currency })}`, NO_TENANT),
  analytics: <T>(report: string, params: Record<string, unknown> = {}) =>
    api.get<{ report: string; data: T }>(`${BASE}/analytics/${qs({ report, ...params })}`, NO_TENANT),

  // Tenants
  tenants: (filters: TenantFilters = {}) =>
    api.get<Page<TenantRow>>(`${BASE}/tenants/${qs(filters as Record<string, unknown>)}`, NO_TENANT),
  tenant: (id: string) => api.get<TenantDetail>(`${BASE}/tenants/${id}/`, NO_TENANT),
  updateTenant: (id: string, body: Record<string, unknown>) =>
    api.patch<TenantDetail>(`${BASE}/tenants/${id}/`, body, NO_TENANT),
  tenantAction: (id: string, action: string, body: Record<string, unknown>) =>
    api.post<TenantDetail>(`${BASE}/tenants/${id}/${action}/`, body, NO_TENANT),

  // Impersonation
  startImpersonation: (tenantId: string, body: Record<string, unknown>) =>
    api.post<ImpersonationGrant>(`${BASE}/tenants/${tenantId}/impersonate/`, body, NO_TENANT),
  impersonations: (params: Record<string, unknown> = {}) =>
    api.get<Page<ImpersonationGrant>>(`${BASE}/impersonations/${qs(params)}`, NO_TENANT),
  endImpersonation: (grantId: string, reason: string) =>
    api.post<ImpersonationGrant>(`${BASE}/impersonations/${grantId}/end/`, { reason }, NO_TENANT),

  // Billing
  plans: (all = false) => api.get<Plan[]>(`${BASE}/plans/${all ? "?all=true" : ""}`, NO_TENANT),
  updatePlan: (planId: string, payload: PlanUpdatePayload) =>
    api.patch<Plan>(`${BASE}/plans/${planId}/`, payload, NO_TENANT),
  planCatalogue: () =>
    api.get<{ tiers: CatalogueTier[]; labels: Record<string, string>; universal: string[] }>(
      `${BASE}/plans/catalogue/`,
      NO_TENANT,
    ),
  subscriptions: (params: Record<string, unknown> = {}) =>
    api.get<Page<SubscriptionDetail & { tenant_id: string }>>(
      `${BASE}/subscriptions/${qs(params)}`,
      NO_TENANT,
    ),
  expiringTrials: (days = 7) =>
    api.get<
      { tenant_id: string; tenant_name: string; plan_name: string; trial_end: string; days_left: number }[]
    >(`${BASE}/subscriptions/expiring-trials/${qs({ days })}`, NO_TENANT),
  invoices: (params: Record<string, unknown> = {}) =>
    api.get<Page<Invoice>>(`${BASE}/invoices/${qs(params)}`, NO_TENANT),
  invoice: (id: string) => api.get<Invoice>(`${BASE}/invoices/${id}/`, NO_TENANT),
  voidInvoice: (id: string, reason: string) =>
    api.post<Invoice>(`${BASE}/invoices/${id}/void/`, { reason }, NO_TENANT),
  /** The PDF is rendered server-side on demand and never stored. */
  invoicePdf: (id: string) => getBlob(`${BASE}/invoices/${id}/pdf/`),
  sendInvoice: (id: string, body: { to?: string; reason?: string } = {}) =>
    api.post<{ queued: boolean; to: string }>(`${BASE}/invoices/${id}/send/`, body, NO_TENANT),
  payments: (params: Record<string, unknown> = {}) =>
    api.get<Page<PaymentRow>>(`${BASE}/payments/${qs(params)}`, NO_TENANT),
  reconcilePayment: (body: Record<string, unknown>) =>
    api.post<Invoice>(`${BASE}/payments/reconcile/`, body, NO_TENANT),

  // Refunds
  refunds: (params: Record<string, unknown> = {}) =>
    api.get<Page<Refund>>(`${BASE}/refunds/${qs(params)}`, NO_TENANT),
  requestRefund: (body: Record<string, unknown>) =>
    api.post<Refund>(`${BASE}/refunds/`, body, NO_TENANT),
  decideRefund: (id: string, decision: "approve" | "reject", note: string) =>
    api.post<Refund>(`${BASE}/refunds/${id}/${decision}/`, { note }, NO_TENANT),

  // Coupons
  coupons: (params: Record<string, unknown> = {}) =>
    api.get<Page<Coupon>>(`${BASE}/coupons/${qs(params)}`, NO_TENANT),
  createCoupon: (body: Record<string, unknown>) =>
    api.post<Coupon>(`${BASE}/coupons/`, body, NO_TENANT),
  updateCoupon: (id: string, body: Record<string, unknown>) =>
    api.patch<Coupon>(`${BASE}/coupons/${id}/`, body, NO_TENANT),
  deactivateCoupon: (id: string) => api.delete<void>(`${BASE}/coupons/${id}/`, NO_TENANT),

  // Dunning
  dunningCases: (params: Record<string, unknown> = {}) =>
    api.get<Page<DunningCase>>(`${BASE}/dunning/cases/${qs(params)}`, NO_TENANT),
  dunningAction: (caseId: string, action: "recover" | "cancel", reason: string) =>
    api.post<DunningCase>(`${BASE}/dunning/cases/${caseId}/${action}/`, { reason }, NO_TENANT),
  dunningPolicies: () => api.get<Record<string, unknown>[]>(`${BASE}/dunning/policies/`, NO_TENANT),
  createDunningPolicy: (body: Record<string, unknown>) =>
    api.post<Record<string, unknown>>(`${BASE}/dunning/policies/`, body, NO_TENANT),

  // Governance
  staff: (params: Record<string, unknown> = {}) =>
    api.get<Page<PlatformStaff>>(`${BASE}/staff/${qs(params)}`, NO_TENANT),
  appointStaff: (body: Record<string, unknown>) =>
    api.post<PlatformStaff>(`${BASE}/staff/`, body, NO_TENANT),
  updateStaff: (id: string, body: Record<string, unknown>) =>
    api.patch<PlatformStaff>(`${BASE}/staff/${id}/`, body, NO_TENANT),
  revokeStaff: (id: string) => api.delete<void>(`${BASE}/staff/${id}/`, NO_TENANT),
  audit: (params: Record<string, unknown> = {}) =>
    api.get<Page<AuditRow>>(`${BASE}/audit/${qs(params)}`, NO_TENANT),

  // Operations
  health: () => api.get<HealthSnapshot>(`${BASE}/health/`, NO_TENANT),
  notifications: (params: Record<string, unknown> = {}) =>
    api.get<Page<PlatformNotification>>(`${BASE}/notifications/${qs(params)}`, NO_TENANT),
  acknowledge: (id: string) =>
    api.post<PlatformNotification>(`${BASE}/notifications/${id}/ack/`, {}, NO_TENANT),
  acknowledgeAll: () => api.post<{ acknowledged: number }>(`${BASE}/notifications/ack/`, {}, NO_TENANT),

  // Settings
  settings: () => api.get<{ settings: PlatformSetting[] }>(`${BASE}/settings/`, NO_TENANT),
  writeSetting: (body: { key: string; value: unknown; reason?: string }) =>
    api.post<PlatformSetting>(`${BASE}/settings/`, body, NO_TENANT),
  testEmail: () => api.post<{ ok: boolean; to: string }>(`${BASE}/settings/test-email/`, {}, NO_TENANT),
  testAI: () =>
    api.post<{ ok: boolean; model?: string; reply?: string }>(`${BASE}/settings/test-ai/`, {}, NO_TENANT),

  // Saved views
  savedViews: (surface?: string) =>
    api.get<SavedView[]>(`${BASE}/saved-views/${qs({ surface })}`, NO_TENANT),
  saveView: (body: Record<string, unknown>) =>
    api.post<SavedView>(`${BASE}/saved-views/`, body, NO_TENANT),
  deleteSavedView: (id: string) => api.delete<void>(`${BASE}/saved-views/${id}/`, NO_TENANT),
};
