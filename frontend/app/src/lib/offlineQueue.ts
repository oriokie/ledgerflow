/**
 * Offline Quick Add queue.
 *
 * Deliberately narrow in scope: this queues *one* kind of write — Quick Add
 * transactions — not a generic "retry any request" mechanism. A financial
 * ledger is the wrong place for a general-purpose offline-write system:
 * arbitrary requests have arbitrary side effects, and replaying one blindly
 * after a network gap could double-apply something that was never meant to be
 * idempotent. Quick Add is safe to queue specifically because the backend
 * accepts a client-generated `idempotency_key` and guarantees a replay lands
 * on the same transaction rather than posting twice (see
 * apps/finance/quick_add.py and the ledger's `_existing_transactions_for`
 * guard) — that server-side contract is what makes this queue safe to build
 * at all, not an assumption made only on the client.
 *
 * IndexedDB rather than localStorage: entries can include enough data to
 * survive a page reload and a service worker restart, and unlike
 * localStorage, IndexedDB is available to the service worker itself, which is
 * what actually drains the queue on reconnect via Background Sync.
 */

const DB_NAME = "ledgerflow-offline";
const DB_VERSION = 1;
const STORE = "quick-add-queue";

export interface QueuedQuickAdd {
  /** Client-generated, sent unchanged on every retry — this is the whole
   * safety property the queue depends on. */
  idempotencyKey: string;
  amountMinor: number;
  merchant: string;
  isIncome: boolean;
  financialAccountId?: string;
  categoryId?: string;
  occurredAt: string;
  queuedAt: string;
  /** Bumped on each failed retry so a stuck entry can eventually be surfaced
   * to the user rather than retried silently forever. */
  attempts: number;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "idempotencyKey" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore<T>(
  mode: IDBTransactionMode,
  fn: (store: IDBObjectStore) => IDBRequest<T> | void,
): Promise<T> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const store = tx.objectStore(STORE);
    const request = fn(store);
    tx.oncomplete = () => resolve(request ? (request.result as T) : (undefined as T));
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

/** Generate a client-side idempotency key.
 *
 * `crypto.randomUUID()` when available (every modern mobile browser);
 * otherwise a timestamp-plus-random fallback that's unique enough for this
 * purpose without needing a polyfill.
 */
export function generateIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `quick-add:${crypto.randomUUID()}`;
  }
  return `quick-add:${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Add a Quick Add submission to the offline queue. */
export async function enqueueQuickAdd(
  entry: Omit<QueuedQuickAdd, "queuedAt" | "attempts">,
): Promise<void> {
  const full: QueuedQuickAdd = { ...entry, queuedAt: new Date().toISOString(), attempts: 0 };
  await withStore("readwrite", (store) => store.put(full));
}

/** Everything currently queued, oldest first — the order a person entered
 * them in, which is the order they should post in. */
export async function listQueued(): Promise<QueuedQuickAdd[]> {
  const all = await withStore<QueuedQuickAdd[]>("readonly", (store) => store.getAll());
  return [...all].sort((a, b) => a.queuedAt.localeCompare(b.queuedAt));
}

export async function queueLength(): Promise<number> {
  return withStore<number>("readonly", (store) => store.count());
}

/** Remove one entry — called after it posts successfully. */
export async function dequeue(idempotencyKey: string): Promise<void> {
  await withStore("readwrite", (store) => store.delete(idempotencyKey));
}

/** Record a failed attempt without removing the entry, so a transient
 * failure (still offline, a 5xx) gets retried rather than lost. */
export async function markAttempt(idempotencyKey: string): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    const getRequest = store.get(idempotencyKey);
    getRequest.onsuccess = () => {
      const existing = getRequest.result as QueuedQuickAdd | undefined;
      if (existing) store.put({ ...existing, attempts: existing.attempts + 1 });
    };
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function clearQueue(): Promise<void> {
  await withStore("readwrite", (store) => store.clear());
}
