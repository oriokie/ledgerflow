/**
 * Web Push subscription — the browser-side half of apps.notifications.push.
 *
 * Deliberately thin: this only converts between the browser's PushManager
 * API and the shapes the backend expects. Permission prompting is the
 * caller's responsibility (see PushToggle.tsx), because *when* to ask is a
 * product decision — asking on page load is how people learn to reflexively
 * deny every permission prompt a site ever shows them.
 */

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  // Built via `new Uint8Array(length)` rather than `Uint8Array.from(...)`:
  // `.from()` infers a type that could theoretically back onto a
  // SharedArrayBuffer, which the Push API's stricter typed signature for
  // `applicationServerKey` rejects — this construction is guaranteed
  // ArrayBuffer-backed.
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

export function isPushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window;
}

export async function currentPermission(): Promise<NotificationPermission | "unsupported"> {
  if (!isPushSupported()) return "unsupported";
  return Notification.permission;
}

/** Subscribe this browser to push, prompting for permission if not already
 * granted. Returns the subscription JSON ready to send to the backend, or
 * `null` if the user declined or push isn't supported here. */
export async function subscribeToPush(
  vapidPublicKey: string,
): Promise<{ endpoint: string; keys: { p256dh: string; auth: string } } | null> {
  if (!isPushSupported()) return null;

  const permission = await Notification.requestPermission();
  if (permission !== "granted") return null;

  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
  });

  const json = subscription.toJSON();
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) return null;
  return { endpoint: json.endpoint, keys: { p256dh: json.keys.p256dh, auth: json.keys.auth } };
}

/** Unsubscribe this browser and return the endpoint that was removed, so the
 * caller can tell the backend which subscription to drop. */
export async function unsubscribeFromPush(): Promise<string | null> {
  if (!isPushSupported()) return null;
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  if (!subscription) return null;
  const endpoint = subscription.endpoint;
  await subscription.unsubscribe();
  return endpoint;
}

export async function existingSubscriptionEndpoint(): Promise<string | null> {
  if (!isPushSupported()) return null;
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  return subscription?.endpoint ?? null;
}
