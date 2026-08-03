import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { pushApi } from "../api/push";
import {
  currentPermission,
  existingSubscriptionEndpoint,
  isPushSupported,
  subscribeToPush,
  unsubscribeFromPush,
} from "../lib/pushSubscription";
import { useAuth } from "../lib/AuthContext";

/** The VAPID public key for this deployment, or null when push isn't
 * configured — the caller hides the toggle entirely rather than offering a
 * control that will always fail. */
export function usePushPublicKey() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["push-public-key"],
    queryFn: () => pushApi.publicKey(),
    enabled: !!activeWorkspace,
    staleTime: Infinity, // a deployment's VAPID key never changes at runtime
  });
}

/**
 * Whether *this browser* is currently subscribed, read from the browser's
 * own PushManager rather than assumed from local state — a subscription can
 * be revoked outside the app (browser settings, OS-level permission reset),
 * and the toggle should reflect reality on every visit rather than drift
 * from it.
 */
export function usePushSubscriptionState() {
  const [endpoint, setEndpoint] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    if (!isPushSupported()) {
      setEndpoint(null);
      return;
    }
    existingSubscriptionEndpoint().then(setEndpoint);
  }, []);

  return {
    // undefined = still checking, null = not subscribed, string = subscribed
    endpoint,
    isSubscribed: !!endpoint,
    isChecking: endpoint === undefined,
    supported: isPushSupported(),
  };
}

export function useTogglePush() {
  const queryClient = useQueryClient();

  const subscribe = useMutation({
    mutationFn: async (vapidPublicKey: string) => {
      const subscription = await subscribeToPush(vapidPublicKey);
      if (!subscription) return null;
      await pushApi.subscribe(subscription);
      return subscription.endpoint;
    },
  });

  const unsubscribe = useMutation({
    mutationFn: async () => {
      const endpoint = await unsubscribeFromPush();
      if (endpoint) await pushApi.unsubscribe(endpoint);
      return endpoint;
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["push-public-key"] }),
  });

  return { subscribe, unsubscribe };
}

export { currentPermission };
