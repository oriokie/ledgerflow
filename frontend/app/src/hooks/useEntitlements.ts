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

/**
 * The feature map, mirrored from the backend's entitlement rules exactly:
 *
 * - no subscription → everything (a legacy install that never seeded billing)
 * - active/trialing (trial clock not expired) → the plan's resolved features
 * - anything else, or a trial past its end → lapsed: no gated features
 *
 * The backend enforces all of this with 402s; this mirror exists so the UI
 * can hide dead nav entries and show an upgrade path instead of an error.
 */
export function useFeatures(): {
  has: (feature: string) => boolean;
  lapsed: boolean;
  trialing: boolean;
  trialDaysLeft: number | null;
  isLoading: boolean;
} {
  const { data: subscription, isLoading } = useSubscription();
  if (!subscription) {
    return { has: () => true, lapsed: false, trialing: false, trialDaysLeft: null, isLoading };
  }

  const trialEnd = subscription.trial_end ? new Date(subscription.trial_end) : null;
  const trialExpired =
    subscription.status === "trialing" && trialEnd !== null && trialEnd.getTime() < Date.now();
  const entitled =
    (subscription.status === "active" || subscription.status === "trialing") && !trialExpired;

  if (!entitled) {
    return { has: () => false, lapsed: true, trialing: false, trialDaysLeft: null, isLoading };
  }

  const keys = new Set(subscription.plan.resolved_features.map((f) => f.key));
  const daysLeft =
    subscription.status === "trialing" && trialEnd
      ? Math.max(0, Math.ceil((trialEnd.getTime() - Date.now()) / 86_400_000))
      : null;
  return {
    has: (feature) => keys.has(feature),
    lapsed: false,
    trialing: subscription.status === "trialing",
    trialDaysLeft: daysLeft,
    isLoading,
  };
}

/** Which plan feature each gated route needs. One map, used by the sidebar,
 * the tab bar and the command palette, so the three can never disagree about
 * what a Basic customer sees. */
export const FEATURE_BY_PATH: Record<string, string> = {
  "/investments": "investments",
  "/debt": "debt_planner",
  "/receipts/scan": "receipt_scanning",
  "/automation": "automation_rules",
  "/cashflow": "cashflow_forecast",
  "/reports": "advanced_reports",
  "/analytics": "advanced_reports",
  "/insights": "ai_insights",
  "/coach": "ai_coach",
  "/review": "smart_planning",
};
