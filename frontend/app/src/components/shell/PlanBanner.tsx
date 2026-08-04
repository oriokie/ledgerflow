import { Link } from "react-router-dom";
import { useFeatures } from "../../hooks/useEntitlements";

/**
 * The trial clock and the lapsed wall, in one quiet strip.
 *
 * During the trial it counts down and points at /billing — visible without
 * being a nag, because the countdown is genuinely useful information. Once
 * lapsed it turns firm: recording is paused, reading and export are not, and
 * the copy says exactly that, because the moment someone fears their data is
 * hostage is the moment they leave angry instead of subscribing.
 */
export function PlanBanner() {
  const { lapsed, trialing, trialDaysLeft } = useFeatures();

  if (lapsed) {
    return (
      <div className="lf-plan-banner" data-tone="lapsed" role="status">
        Your trial has ended — recording is paused, but everything you saved is intact and
        exportable. <Link to="/billing">Choose a plan</Link> to pick up where you left off.
      </div>
    );
  }

  if (trialing && trialDaysLeft !== null) {
    return (
      <div className="lf-plan-banner" data-tone="trial" role="status">
        Trial — {trialDaysLeft} day{trialDaysLeft === 1 ? "" : "s"} left.{" "}
        <Link to="/billing">Choose a plan</Link>
      </div>
    );
  }

  return null;
}
