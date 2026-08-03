import { useState } from "react";
import { usePushPublicKey, usePushSubscriptionState, useTogglePush } from "../../hooks/usePush";
import { Banner, Switch, Text } from "../../ui";

/**
 * The push notification toggle, for Settings → Preferences.
 *
 * Renders nothing at all when this deployment has no VAPID key configured —
 * offering a switch that can never work is worse than not mentioning push,
 * the same rule the debt planner follows for a report with nothing to show.
 *
 * *When* to ask for permission is a deliberate product decision, made here:
 * only on this explicit toggle, never on page load. Prompting on load is how
 * people learn to reflexively deny every permission a site ever asks for
 * again, which would poison every other prompt this product might need.
 */
export function PushToggle() {
  const { data: keyResponse, isLoading: keyLoading } = usePushPublicKey();
  const { isSubscribed, isChecking, supported } = usePushSubscriptionState();
  const { subscribe, unsubscribe } = useTogglePush();
  const [error, setError] = useState<string | null>(null);

  if (keyLoading || !keyResponse) return null;
  if (!supported) {
    return (
      <Text tone="tertiary" size="xs">
        Push notifications aren't available in this browser.
      </Text>
    );
  }

  const busy = subscribe.isPending || unsubscribe.isPending || isChecking;

  const onChange = async (checked: boolean) => {
    setError(null);
    try {
      if (checked) {
        const endpoint = await subscribe.mutateAsync(keyResponse.public_key);
        if (!endpoint) setError("Notifications were blocked — check your browser's site settings.");
      } else {
        await unsubscribe.mutateAsync();
      }
    } catch {
      setError("Couldn't update your notification settings.");
    }
  };

  return (
    <div>
      <Switch
        label="Push notifications"
        checked={isSubscribed}
        onChange={(event) => onChange(event.target.checked)}
        disabled={busy}
      />
      {error && (
        <Banner tone="danger" className="lf-push-toggle-error">
          {error}
        </Banner>
      )}
    </div>
  );
}
