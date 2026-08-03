/**
 * LedgerFlow service worker.
 *
 * No build-time precache manifest (the kind vite-plugin-pwa generates):
 * Vite content-hashes every build asset, so a hand-written service worker
 * that hardcodes filenames would need regenerating on every deploy and would
 * silently go stale otherwise. Runtime caching sidesteps that entirely — the
 * cache fills itself from whatever the browser actually requests, and a new
 * deploy naturally produces new hashed URLs that simply aren't in the old
 * cache yet, with no explicit invalidation step required.
 *
 * Three strategies, chosen per request and never mixed:
 *
 *   navigations (HTML)     network-first, falling back to the cached shell —
 *                          the app should always try for the latest build,
 *                          but must still open with no connection at all.
 *   same-origin static     stale-while-revalidate — instant repeat loads,
 *   assets (js/css/img)    self-healing on redeploy via content hashing.
 *   API requests           network-only, always. Financial data must never
 *                          be served stale from a cache; "can't reach the
 *                          server" is handled explicitly by the offline
 *                          queue, not papered over with a cached response
 *                          that might be materially wrong.
 *
 * Background Sync drains the Quick Add offline queue when connectivity
 * returns, and Push shows a notification from the payload the backend
 * builds in apps/notifications/push.py.
 */

/// <reference lib="webworker" />
export {};
declare const self: ServiceWorkerGlobalScope;

// The Background Sync API isn't in TypeScript's bundled DOM/webworker types
// (still non-standard as of this writing, Safari has no support at all —
// which is exactly why this file also drains the queue via an explicit
// postMessage as a fallback, see below). Minimal ambient shape for the one
// property this file actually reads.
interface SyncEvent extends ExtendableEvent {
  readonly tag: string;
}

const RUNTIME_CACHE = "lf-runtime-v1";
const SHELL_CACHE = "lf-shell-v1";
const OFFLINE_URL = "/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(["/", OFFLINE_URL])),
  );
  // Activate a new version immediately rather than waiting for every open
  // tab to close — a financial app's users don't sit on stale tabs, and the
  // network-only API strategy means there's no risk of a new SW serving old
  // data underneath an old page.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => ![RUNTIME_CACHE, SHELL_CACHE].includes(key))
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

function isApiRequest(url: URL): boolean {
  return url.pathname.startsWith("/api/");
}

function isNavigationRequest(request: Request): boolean {
  return request.mode === "navigate";
}

async function networkFirstNavigation(request: Request): Promise<Response> {
  try {
    const response = await fetch(request);
    // Keep the shell fresh for the next offline visit.
    const cache = await caches.open(SHELL_CACHE);
    cache.put("/", response.clone());
    return response;
  } catch {
    const cache = await caches.open(SHELL_CACHE);
    return (await cache.match(request)) ?? (await cache.match("/")) ?? (await cache.match(OFFLINE_URL))!;
  }
}

async function staleWhileRevalidate(request: Request): Promise<Response> {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => undefined);
  // Cached copy first for speed; the network request still runs and updates
  // the cache for next time even though this response doesn't wait for it.
  return cached ?? (await network) ?? Response.error();
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  if (event.request.method !== "GET") return; // never intercept writes
  if (isApiRequest(url)) return; // network-only: let it hit the network untouched

  if (isNavigationRequest(event.request)) {
    event.respondWith(networkFirstNavigation(event.request));
    return;
  }

  if (url.origin === self.location.origin) {
    event.respondWith(staleWhileRevalidate(event.request));
  }
});

// --------------------------------------------------------------- background sync
const SYNC_TAG = "quick-add-queue";

self.addEventListener("sync", (event) => {
  const syncEvent = event as SyncEvent;
  if (syncEvent.tag === SYNC_TAG) {
    syncEvent.waitUntil(drainQuickAddQueue());
  }
});

// Also drained on activation and on an explicit message from the app: some
// browsers (notably iOS Safari, as of this writing) don't implement
// Background Sync at all, so the app additionally calls this directly when
// it detects the connection come back — Background Sync is an enhancement
// on top of that, not the only path.
self.addEventListener("message", (event) => {
  if (event.data?.type === "DRAIN_QUICK_ADD_QUEUE") {
    event.waitUntil?.(drainQuickAddQueue());
  }
});

interface QueuedQuickAdd {
  idempotencyKey: string;
  amountMinor: number;
  merchant: string;
  isIncome: boolean;
  financialAccountId?: string;
  categoryId?: string;
  occurredAt: string;
}

/** Minimal, dependency-free IndexedDB read matching the shape written by
 * src/lib/offlineQueue.ts. Duplicated rather than imported: a service worker
 * is a separate execution context with its own module graph, and Vite builds
 * it as a standalone entry — sharing the exact DB name and store name is the
 * actual contract between the two files, documented here and there. */
function openQueueDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("ledgerflow-offline", 1);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function readQueue(): Promise<QueuedQuickAdd[]> {
  const db = await openQueueDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("quick-add-queue", "readonly");
    const req = tx.objectStore("quick-add-queue").getAll();
    req.onsuccess = () => resolve(req.result as QueuedQuickAdd[]);
    req.onerror = () => reject(req.error);
  });
}

async function removeFromQueue(key: string): Promise<void> {
  const db = await openQueueDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("quick-add-queue", "readwrite");
    tx.objectStore("quick-add-queue").delete(key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function apiBaseUrl(): Promise<string> {
  // The SW has no import.meta.env of its own build context in the way the
  // app does at runtime; the app posts its configured base URL in on
  // registration so both agree on where the API lives.
  const clients = await self.clients.matchAll();
  return (await getStoredApiBase()) ?? clients[0]?.url ?? self.location.origin;
}

let cachedApiBase: string | null = null;
async function getStoredApiBase(): Promise<string | null> {
  return cachedApiBase;
}

self.addEventListener("message", (event) => {
  if (event.data?.type === "SET_API_BASE") {
    cachedApiBase = event.data.apiBase;
  }
});

async function drainQuickAddQueue(): Promise<void> {
  const queued = await readQueue();
  if (queued.length === 0) return;

  const base = await apiBaseUrl();
  const clients = await self.clients.matchAll();

  for (const entry of queued) {
    try {
      const response = await fetch(`${base}/finance/quick-add/`, {
        method: "POST",
        headers: await authHeaders(),
        body: JSON.stringify({
          amount_minor: entry.amountMinor,
          merchant: entry.merchant,
          is_income: entry.isIncome,
          financial_account_id: entry.financialAccountId ?? null,
          category_id: entry.categoryId ?? null,
          occurred_at: entry.occurredAt,
          idempotency_key: entry.idempotencyKey,
        }),
      });
      // 2xx *or* 409 (a legitimate business-rule rejection, not a network
      // failure) both mean "stop retrying this one" — only a network error or
      // 5xx should leave it in the queue for the next sync attempt.
      if (response.ok || response.status === 409 || response.status === 400) {
        await removeFromQueue(entry.idempotencyKey);
        notifyClients(clients, { type: "QUICK_ADD_SYNCED", idempotencyKey: entry.idempotencyKey });
      }
    } catch {
      // Offline again, or the request otherwise failed to complete — leave it
      // queued for the next sync trigger rather than losing it.
      break;
    }
  }
}

let cachedAuthToken: string | null = null;
self.addEventListener("message", (event) => {
  if (event.data?.type === "SET_AUTH_TOKEN") {
    cachedAuthToken = event.data.token;
  }
});

async function authHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (cachedAuthToken) headers.Authorization = `Bearer ${cachedAuthToken}`;
  return headers;
}

function notifyClients(clients: readonly Client[], message: unknown): void {
  for (const client of clients) client.postMessage(message);
}

// --------------------------------------------------------------------- push
self.addEventListener("push", (event) => {
  if (!event.data) return;
  let payload: { title?: string; body?: string; tag?: string; data?: Record<string, unknown> };
  try {
    payload = event.data.json();
  } catch {
    return;
  }

  event.waitUntil(
    self.registration.showNotification(payload.title ?? "LedgerFlow", {
      body: payload.body ?? "",
      tag: payload.tag,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: payload.data ?? {},
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const notificationId = (event.notification.data as { notification_id?: string })?.notification_id;
  const url = notificationId ? `/?notification=${notificationId}` : "/";

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      const existing = clients.find((c) => "focus" in c);
      if (existing) return (existing as WindowClient).focus();
      return self.clients.openWindow(url);
    }),
  );
});
