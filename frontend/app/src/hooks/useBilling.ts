import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { billingApi, hasSubscription } from "../api/billing";
import type { Subscription } from "../api/types";
import { useAuth } from "../lib/AuthContext";

export function usePlans(currency = "USD") {
  return useQuery({
    queryKey: ["plans", currency],
    queryFn: () => billingApi.listPlans(currency),
    staleTime: 10 * 60_000, // catalog rarely changes
  });
}

export function useSubscription() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["subscription", activeWorkspace?.tenant.id],
    queryFn: async (): Promise<Subscription | null> => {
      const res = await billingApi.getSubscription();
      return hasSubscription(res) ? res : null;
    },
    enabled: !!activeWorkspace,
  });
}

export function usePaymentMethods() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["payment-methods", activeWorkspace?.tenant.id],
    queryFn: () => billingApi.listPaymentMethods(),
    enabled: !!activeWorkspace,
  });
}

export function usePayments() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["payments", activeWorkspace?.tenant.id],
    queryFn: () => billingApi.listPayments(),
    enabled: !!activeWorkspace,
  });
}

function invalidateBilling(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["subscription"] });
  qc.invalidateQueries({ queryKey: ["payment-methods"] });
  qc.invalidateQueries({ queryKey: ["payments"] });
}

export function useSubscribe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ planId, paymentMethodId }: { planId: string; paymentMethodId?: string }) =>
      billingApi.subscribe(planId, paymentMethodId),
    onSuccess: () => invalidateBilling(qc),
  });
}

export function useCancelSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (atPeriodEnd: boolean) => billingApi.cancel(atPeriodEnd),
    onSuccess: () => invalidateBilling(qc),
  });
}

export function useRetrySubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => billingApi.retry(),
    onSuccess: () => invalidateBilling(qc),
  });
}

export function useAddPaymentMethod() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: billingApi.addPaymentMethod,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["payment-methods"] }),
  });
}

export function useSetDefaultPaymentMethod() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (methodId: string) => billingApi.setDefaultPaymentMethod(methodId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["payment-methods"] }),
  });
}

export function useRemovePaymentMethod() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (methodId: string) => billingApi.removePaymentMethod(methodId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["payment-methods"] }),
  });
}
