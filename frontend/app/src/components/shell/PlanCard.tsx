import { Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { useSubscription } from "../../hooks/useBilling";

/**
 * Which plan this workspace is on, and a way off it.
 *
 * The plan was knowable only by navigating to Billing, which is the one place
 * you go *after* you already know you want to change something. Putting it in
 * the rail answers "what am I paying for" where the question actually occurs —
 * next to the features it decides, several of which the rail is quietly hiding.
 *
 * The upgrade CTA is shown for Basic and for a trial, and withheld from Plus:
 * an upgrade button on the top plan is an advert, not an affordance. A
 * workspace with no subscription at all (a legacy install that never seeded
 * billing) shows nothing — it is unmetered, so there is no plan to report and
 * nothing to upgrade to.
 */
export function PlanCard({ onNavigate }: { onNavigate?: () => void }) {
  const { data: subscription, isLoading } = useSubscription();

  // Nothing at all while it loads. A placeholder that resolves into "Basic"
  // would flash a plan the workspace may not be on.
  if (isLoading || !subscription) return null;

  const tier = subscription.plan.tier;
  const trialing = subscription.status === "trialing";
  const trialEnd = subscription.trial_end ? new Date(subscription.trial_end) : null;
  const daysLeft =
    trialing && trialEnd ? Math.max(0, Math.ceil((trialEnd.getTime() - Date.now()) / 86_400_000)) : null;

  // Only tiers below the top one have somewhere to go.
  const canUpgrade = tier !== "plus";

  return (
    <div className="lf-plan-card" data-tier={tier}>
      <div className="lf-plan-head">
        <span className="lf-plan-name">{subscription.plan.name}</span>
        {trialing && <span className="lf-plan-chip">Trial</span>}
      </div>

      <p className="lf-plan-note">
        {daysLeft !== null
          ? `${daysLeft} ${daysLeft === 1 ? "day" : "days"} left on your trial`
          : `${subscription.plan.max_accounts ?? "Unlimited"} accounts · ${
              subscription.plan.max_members ?? "Unlimited"
            } ${subscription.plan.max_members === 1 ? "person" : "people"}`}
      </p>

      {canUpgrade && (
        <Link to="/billing" className="lf-plan-upgrade" onClick={onNavigate}>
          <Sparkles size={14} strokeWidth={2} aria-hidden="true" />
          Upgrade
        </Link>
      )}
    </div>
  );
}
