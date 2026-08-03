import { useSubscription } from "./useBilling";

/**
 * Client-side mirror of the backend entitlement rule: a tenant with no active
 * subscription is unmetered (full access); a metered tenant only has AI when
 * its plan includes it. The backend enforces this too — this just lets the UI
 * avoid dead calls and show an upgrade path instead of an error.
 */
export function useAiEnabled(): { aiEnabled: boolean; isLoading: boolean } {
  const { data: subscription, isLoading } = useSubscription();
  if (!subscription) return { aiEnabled: true, isLoading };
  const metered = subscription.status === "active" || subscription.status === "trialing";
  if (!metered) return { aiEnabled: true, isLoading };
  return { aiEnabled: subscription.plan.ai_insights, isLoading };
}
