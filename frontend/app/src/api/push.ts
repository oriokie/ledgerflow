import { api } from "./client";

export const pushApi = {
  /** Null when this deployment has no VAPID key configured — the caller
   * hides the "enable notifications" affordance entirely rather than offer a
   * button that will always fail. */
  publicKey: () => api.get<{ public_key: string } | null>("/notifications/push/public-key/"),

  subscribe: (subscription: {
    endpoint: string;
    keys: { p256dh: string; auth: string };
    userAgent?: string;
  }) =>
    api.post<{ id: string }>("/notifications/push/subscribe/", {
      endpoint: subscription.endpoint,
      keys: subscription.keys,
      user_agent: subscription.userAgent ?? navigator.userAgent,
    }),

  unsubscribe: (endpoint: string) =>
    api.post<void>("/notifications/push/unsubscribe/", { endpoint }),
};
