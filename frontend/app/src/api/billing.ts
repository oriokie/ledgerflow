import { api } from "./client";
import type { Payment, PaymentMethod, Plan, Subscription } from "./types";

export const billingApi = {
  /** Public catalog — no tenant needed. */
  listPlans: (currency = "USD") =>
    api.get<Plan[]>(`/billing/plans/?currency=${currency}`, { skipTenant: true }),

  getSubscription: () => api.get<Subscription | { subscription: null }>("/billing/subscription/"),

  subscribe: (planId: string, paymentMethodId?: string) =>
    api.post<Subscription>("/billing/subscription/", {
      plan_id: planId,
      payment_method_id: paymentMethodId ?? null,
    }),

  cancel: (atPeriodEnd = true) =>
    api.post<Subscription>("/billing/subscription/cancel/", { at_period_end: atPeriodEnd }),
  retry: () => api.post<Subscription>("/billing/subscription/retry/", {}),

  listPaymentMethods: () => api.get<PaymentMethod[]>("/billing/payment-methods/"),

  /**
   * `token` is a client-side reference, never raw card data:
   *  - Stripe: a PaymentMethod id from Stripe.js (Elements) collected in-browser
   *  - M-PESA: the customer's phone number (there's no stored-card equivalent)
   * In sandbox mode the backend accepts any token and returns safe display fields.
   */
  addPaymentMethod: (payload: { provider: "stripe" | "mpesa"; token: string; kind: "card" | "mpesa"; make_default?: boolean }) =>
    api.post<PaymentMethod>("/billing/payment-methods/", payload),

  /** Promote a saved method to the one renewals charge. */
  setDefaultPaymentMethod: (methodId: string) =>
    api.patch<PaymentMethod>(`/billing/payment-methods/${methodId}/`, {}),

  removePaymentMethod: (methodId: string) =>
    api.delete<void>(`/billing/payment-methods/${methodId}/`),

  listPayments: () => api.get<Payment[]>("/billing/payments/"),
};

export function hasSubscription(res: Subscription | { subscription: null }): res is Subscription {
  return !("subscription" in res && res.subscription === null);
}
