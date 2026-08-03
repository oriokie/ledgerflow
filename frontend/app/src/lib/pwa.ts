/**
 * PWA bootstrap: registers the service worker, keeps it informed of the
 * current API base and auth token (it has no access to either on its own —
 * see the comment in src/sw.ts), and triggers a queue drain on reconnect.
 *
 * Kept as one small module with clear one-way data flow — app tells SW,
 * never the reverse for anything auth-related — rather than spreading
 * `navigator.serviceWorker` calls across the codebase.
 */

import { tokenStore } from "../api/tokenStore";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

let registration: ServiceWorkerRegistration | null = null;

export async function registerServiceWorker(): Promise<void> {
  if (!("serviceWorker" in navigator)) return; // Safari < 16.4, some in-app browsers

  try {
    registration = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
    sendApiBase();
    sendAuthToken();

    // Background Sync isn't implemented everywhere (notably Safari); the
    // reconnect listener below is the fallback that makes offline sync work
    // universally rather than only on Chromium browsers.
    window.addEventListener("online", () => drainQueueNow());
  } catch (error) {
    // A failed SW registration must never block the app from working online
    // — it only means offline support and push are unavailable this session.
    console.warn("Service worker registration failed", error);
  }
}

function postToServiceWorker(message: unknown): void {
  navigator.serviceWorker.controller?.postMessage(message);
}

function sendApiBase(): void {
  postToServiceWorker({ type: "SET_API_BASE", apiBase: API_BASE });
}

function sendAuthToken(): void {
  // Read fresh rather than cached: the token store has no change
  // notifications to subscribe to (see api/tokenStore.ts), so instead of
  // pushing on every login/refresh/logout, this pulls the current value at
  // the moments it's actually about to matter — see the call in
  // `drainQueueNow` below, which re-sends it immediately before every sync
  // attempt.
  postToServiceWorker({ type: "SET_AUTH_TOKEN", token: tokenStore.getAccess() });
}

/** Ask the service worker to drain the offline queue right now.
 *
 * Called on `online` (works everywhere) and additionally registered as a
 * Background Sync tag where the browser supports it, so a queued entry can
 * send even if the tab isn't open when connectivity returns.
 */
export async function drainQueueNow(): Promise<void> {
  if (!registration) return;
  sendAuthToken(); // fresh token immediately before the SW might use it
  postToServiceWorker({ type: "DRAIN_QUICK_ADD_QUEUE" });

  const syncManager = (registration as ServiceWorkerRegistration & { sync?: { register(tag: string): Promise<void> } }).sync;
  if (syncManager) {
    try {
      await syncManager.register("quick-add-queue");
    } catch {
      // Sync registration can fail (permission, browser policy); the
      // immediate postMessage above already covers this attempt regardless.
    }
  }
}

/** Listen for the service worker confirming a queued entry has synced, so
 * the UI can update its pending count without polling. */
export function onQuickAddSynced(callback: (idempotencyKey: string) => void): () => void {
  if (!("serviceWorker" in navigator)) return () => {};
  const handler = (event: MessageEvent) => {
    if (event.data?.type === "QUICK_ADD_SYNCED") callback(event.data.idempotencyKey);
  };
  navigator.serviceWorker.addEventListener("message", handler);
  return () => navigator.serviceWorker.removeEventListener("message", handler);
}

// ------------------------------------------------------------------- install
let deferredInstallPrompt: BeforeInstallPromptEvent | null = null;

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

/** Capture the browser's install prompt so the app can offer it from its own
 * UI at a moment that makes sense, rather than the browser's own timing. */
export function captureInstallPrompt(onAvailable: () => void): void {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredInstallPrompt = event as BeforeInstallPromptEvent;
    onAvailable();
  });
}

export function isInstallable(): boolean {
  return deferredInstallPrompt !== null;
}

export async function promptInstall(): Promise<boolean> {
  if (!deferredInstallPrompt) return false;
  await deferredInstallPrompt.prompt();
  const { outcome } = await deferredInstallPrompt.userChoice;
  deferredInstallPrompt = null;
  return outcome === "accepted";
}

export function isRunningStandalone(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    // iOS Safari's own non-standard flag, still the only signal it exposes.
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}
