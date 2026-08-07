/**
 * Data hooks for the platform workspace.
 *
 * Two things worth noting:
 *
 * 1. **`useCapability` is the single gate for every admin control.** It reads
 *    the resolved capability list the server sends on `/me/`, so the client
 *    never reimplements the role→capability mapping and cannot drift from the
 *    server's answer. Hiding a control is a courtesy, not a security boundary —
 *    the API enforces the same capability independently.
 *
 * 2. **Mutations invalidate broadly rather than surgically.** An admin action
 *    like suspending a tenant changes the tenant row, the dashboard counts,
 *    the audit log and possibly the dunning queue. Reasoning about that graph
 *    per-action is how stale admin screens happen, and these queries are cheap
 *    relative to an operator acting on a number that is no longer true.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import {
  platformApi,
  type Dashboard,
  type PlanUpdatePayload,
  type PlatformStaff,
  type TenantFilters,
} from "../api/platform";

const KEYS = {
  me: ["platform", "me"] as const,
  capabilities: ["platform", "capabilities"] as const,
  dashboard: (currency: string) => ["platform", "dashboard", currency] as const,
  analytics: (report: string, params: unknown) => ["platform", "analytics", report, params] as const,
  tenants: (filters: TenantFilters) => ["platform", "tenants", filters] as const,
  tenant: (id: string) => ["platform", "tenant", id] as const,
  invoices: (params: unknown) => ["platform", "invoices", params] as const,
  payments: (params: unknown) => ["platform", "payments", params] as const,
  refunds: (params: unknown) => ["platform", "refunds", params] as const,
  coupons: (params: unknown) => ["platform", "coupons", params] as const,
  dunning: (params: unknown) => ["platform", "dunning", params] as const,
  staff: ["platform", "staff"] as const,
  audit: (params: unknown) => ["platform", "audit", params] as const,
  health: ["platform", "health"] as const,
  notifications: (params: unknown) => ["platform", "notifications", params] as const,
  impersonations: (params: unknown) => ["platform", "impersonations", params] as const,
  plans: ["platform", "plans"] as const,
  savedViews: (surface?: string) => ["platform", "saved-views", surface] as const,
  expiringTrials: (days: number) => ["platform", "expiring-trials", days] as const,
};

/** Everything under this key is dropped after any admin mutation. */
function invalidateAll(client: ReturnType<typeof useQueryClient>) {
  return client.invalidateQueries({ queryKey: ["platform"] });
}

// ------------------------------------------------------------------- identity
export function usePlatformMe() {
  return useQuery({
    queryKey: KEYS.me,
    queryFn: platformApi.me,
    // A 403 here means "not platform staff", which no amount of retrying fixes.
    retry: false,
    staleTime: 5 * 60_000,
  });
}

/**
 * Returns a predicate over the caller's capabilities.
 *
 * Defaults to `false` while `/me/` is loading, so controls appear as authority
 * is confirmed rather than flashing into view and then disappearing — the
 * latter reads as a bug and, worse, invites a click that will 403.
 */
export function useCapability(staff?: PlatformStaff) {
  return useCallback(
    (capability: string) => Boolean(staff?.capabilities?.includes(capability)),
    [staff],
  );
}

export function useCapabilityCatalog() {
  return useQuery({
    queryKey: KEYS.capabilities,
    queryFn: platformApi.capabilities,
    staleTime: 60 * 60_000, // the RBAC matrix changes on deploy, not at runtime
  });
}

// ------------------------------------------------------------------ dashboard
export function useDashboard(currency = "USD") {
  return useQuery<Dashboard>({
    queryKey: KEYS.dashboard(currency),
    queryFn: () => platformApi.dashboard(currency),
    // Matches the server's 2-minute cache; polling faster only burns requests.
    refetchInterval: 120_000,
  });
}

/**
 * The platform-wide illustration style.
 *
 * Public and unauthenticated, because the landing page and the login form need
 * it before anyone has signed in. Cached hard: it changes when an operator
 * decides it does, which is roughly never, and a request per navigation for a
 * seven-character string would be absurd.
 */
export function useIllustrationStyleSetting() {
  return useQuery({
    queryKey: ["platform", "appearance"],
    queryFn: () => platformApi.appearance(),
    staleTime: 30 * 60_000,
    gcTime: 60 * 60_000,
    retry: false,
  });
}

export function useAnalytics<T>(report: string, params: Record<string, unknown> = {}, enabled = true) {
  return useQuery({
    queryKey: KEYS.analytics(report, params),
    queryFn: () => platformApi.analytics<T>(report, params),
    enabled,
  });
}

// -------------------------------------------------------------------- tenants
export function useTenants(filters: TenantFilters = {}) {
  return useQuery({
    queryKey: KEYS.tenants(filters),
    queryFn: () => platformApi.tenants(filters),
    // Keeps the previous page visible while the next loads, so the table
    // doesn't collapse to a spinner on every keystroke in the search box.
    placeholderData: (previous) => previous,
  });
}

export function useTenant(id: string | undefined) {
  return useQuery({
    queryKey: KEYS.tenant(id ?? ""),
    queryFn: () => platformApi.tenant(id!),
    enabled: Boolean(id),
  });
}

export function useTenantAction(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ action, body }: { action: string; body: Record<string, unknown> }) =>
      platformApi.tenantAction(tenantId, action, body),
    onSuccess: () => invalidateAll(client),
  });
}

export function useUpdateTenant(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => platformApi.updateTenant(tenantId, body),
    onSuccess: () => invalidateAll(client),
  });
}

// -------------------------------------------------------------- impersonation
export function useStartImpersonation(tenantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => platformApi.startImpersonation(tenantId, body),
    onSuccess: () => invalidateAll(client),
  });
}

export function useImpersonations(params: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: KEYS.impersonations(params),
    queryFn: () => platformApi.impersonations(params),
  });
}

export function useEndImpersonation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      platformApi.endImpersonation(id, reason),
    onSuccess: () => invalidateAll(client),
  });
}

// -------------------------------------------------------------------- billing
export function usePlatformPlans(all = false) {
  return useQuery({
    queryKey: [...KEYS.plans, all],
    queryFn: () => platformApi.plans(all),
    staleTime: 10 * 60_000,
  });
}

export function usePlanCatalogue() {
  return useQuery({
    queryKey: ["platform", "plan-catalogue"],
    queryFn: () => platformApi.planCatalogue(),
    staleTime: 30 * 60_000,
  });
}

export function useUpdatePlan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ planId, payload }: { planId: string; payload: PlanUpdatePayload }) =>
      platformApi.updatePlan(planId, payload),
    onSuccess: () => invalidateAll(client),
  });
}

export function useInvoices(params: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: KEYS.invoices(params),
    queryFn: () => platformApi.invoices(params),
    placeholderData: (previous) => previous,
  });
}

export function usePayments(params: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: KEYS.payments(params),
    queryFn: () => platformApi.payments(params),
    placeholderData: (previous) => previous,
  });
}

export function useRefunds(params: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: KEYS.refunds(params),
    queryFn: () => platformApi.refunds(params),
    placeholderData: (previous) => previous,
  });
}

export function useDecideRefund() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      decision,
      note,
    }: {
      id: string;
      decision: "approve" | "reject";
      note: string;
    }) => platformApi.decideRefund(id, decision, note),
    onSuccess: () => invalidateAll(client),
  });
}

/**
 * Download an invoice PDF.
 *
 * Not a query: this is an imperative action with a side effect (a file lands
 * in the user's downloads), and caching a Blob would hold the whole document
 * in memory for a result nobody re-reads.
 *
 * `getBlob` carries the auth header, so this cannot be a plain anchor href —
 * the endpoint is authenticated and a bare link would 401.
 */
export function useDownloadInvoice() {
  return useMutation({
    mutationFn: async ({ id, number }: { id: string; number: string }) => {
      const blob = await platformApi.invoicePdf(id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${number}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      // Release the object URL, or every download leaks until page unload.
      URL.revokeObjectURL(url);
      return { id };
    },
  });
}

export function useSendInvoice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, to }: { id: string; to?: string }) => platformApi.sendInvoice(id, { to }),
    onSuccess: () => invalidateAll(client),
  });
}

export function useVoidInvoice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      platformApi.voidInvoice(id, reason),
    onSuccess: () => invalidateAll(client),
  });
}

// -------------------------------------------------------------------- coupons
export function useCoupons(params: Record<string, unknown> = {}) {
  return useQuery({ queryKey: KEYS.coupons(params), queryFn: () => platformApi.coupons(params) });
}

export function useCreateCoupon() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => platformApi.createCoupon(body),
    onSuccess: () => invalidateAll(client),
  });
}

export function useDeactivateCoupon() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => platformApi.deactivateCoupon(id),
    onSuccess: () => invalidateAll(client),
  });
}

// -------------------------------------------------------------------- dunning
export function useDunningCases(params: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: KEYS.dunning(params),
    queryFn: () => platformApi.dunningCases(params),
    placeholderData: (previous) => previous,
  });
}

export function useDunningAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      action,
      reason,
    }: {
      id: string;
      action: "recover" | "cancel";
      reason: string;
    }) => platformApi.dunningAction(id, action, reason),
    onSuccess: () => invalidateAll(client),
  });
}

// ----------------------------------------------------------------- governance
export function usePlatformStaff(params: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: [...KEYS.staff, params],
    queryFn: () => platformApi.staff(params),
    placeholderData: (previous) => previous,
  });
}

export function useAppointStaff() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => platformApi.appointStaff(body),
    onSuccess: () => invalidateAll(client),
  });
}

export function useRevokeStaff() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => platformApi.revokeStaff(id),
    onSuccess: () => invalidateAll(client),
  });
}

export function useAuditLog(params: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: KEYS.audit(params),
    queryFn: () => platformApi.audit(params),
    placeholderData: (previous) => previous,
  });
}

// ----------------------------------------------------------------- operations
export function useHealth() {
  return useQuery({
    queryKey: KEYS.health,
    queryFn: platformApi.health,
    // Health is the one screen where staleness is actively harmful.
    refetchInterval: 30_000,
  });
}

export function usePlatformNotifications(params: Record<string, unknown> = {}) {
  return useQuery({
    queryKey: KEYS.notifications(params),
    queryFn: () => platformApi.notifications(params),
    refetchInterval: 60_000,
  });
}

export function useAcknowledgeNotification() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => platformApi.acknowledge(id),
    onSuccess: () => invalidateAll(client),
  });
}

export function useExpiringTrials(days = 7) {
  return useQuery({
    queryKey: KEYS.expiringTrials(days),
    queryFn: () => platformApi.expiringTrials(days),
  });
}

// ------------------------------------------------------------------ settings
export function usePlatformSettings() {
  return useQuery({ queryKey: ["platform", "settings"], queryFn: platformApi.settings });
}

export function useWriteSetting() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { key: string; value: unknown; reason?: string }) =>
      platformApi.writeSetting(body),
    // A settings change can alter what other screens report (AI availability,
    // which providers are offered, the invoice issuer), so refresh broadly.
    onSuccess: () => invalidateAll(client),
  });
}

// --------------------------------------------------------------- saved views
export function useSavedViews(surface?: string) {
  return useQuery({
    queryKey: KEYS.savedViews(surface),
    queryFn: () => platformApi.savedViews(surface),
  });
}

export function useSaveView() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => platformApi.saveView(body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["platform", "saved-views"] }),
  });
}

export function useDeleteSavedView() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => platformApi.deleteSavedView(id),
    onSuccess: () => client.invalidateQueries({ queryKey: ["platform", "saved-views"] }),
  });
}
