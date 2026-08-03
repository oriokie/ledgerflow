import { beforeEach, describe, expect, it } from "vitest";
import {
  clearQueue,
  dequeue,
  enqueueQuickAdd,
  generateIdempotencyKey,
  listQueued,
  markAttempt,
  queueLength,
} from "./offlineQueue";

function entry(overrides: Partial<Parameters<typeof enqueueQuickAdd>[0]> = {}) {
  return {
    idempotencyKey: generateIdempotencyKey(),
    amountMinor: 1_250,
    merchant: "Corner Shop",
    isIncome: false,
    occurredAt: new Date().toISOString(),
    ...overrides,
  };
}

beforeEach(async () => {
  await clearQueue();
});

describe("generateIdempotencyKey", () => {
  it("produces a unique key on every call", () => {
    // The one property the server's replay-safety guarantee depends on: two
    // genuinely different entries must never collide.
    const keys = new Set(Array.from({ length: 50 }, generateIdempotencyKey));
    expect(keys.size).toBe(50);
  });
});

describe("offline queue", () => {
  it("stores an entry and lists it back", async () => {
    await enqueueQuickAdd(entry({ merchant: "Corner Shop" }));
    const queued = await listQueued();
    expect(queued).toHaveLength(1);
    expect(queued[0].merchant).toBe("Corner Shop");
  });

  it("starts every entry at zero attempts", async () => {
    await enqueueQuickAdd(entry());
    const [queued] = await listQueued();
    expect(queued.attempts).toBe(0);
  });

  it("lists entries oldest first — the order someone entered them in", async () => {
    const first = entry({ merchant: "First", occurredAt: "2026-01-01T09:00:00Z" });
    await enqueueQuickAdd(first);
    // A real, if small, delay so queuedAt strictly increases between entries;
    // Date.toISOString() has millisecond resolution.
    await new Promise((r) => setTimeout(r, 5));
    const second = entry({ merchant: "Second", occurredAt: "2026-01-01T10:00:00Z" });
    await enqueueQuickAdd(second);

    const queued = await listQueued();
    expect(queued.map((q) => q.merchant)).toEqual(["First", "Second"]);
  });

  it("reports its own length without listing everything", async () => {
    await enqueueQuickAdd(entry());
    await enqueueQuickAdd(entry());
    expect(await queueLength()).toBe(2);
  });

  it("removes an entry once it has posted successfully", async () => {
    const item = entry();
    await enqueueQuickAdd(item);
    await dequeue(item.idempotencyKey);
    expect(await queueLength()).toBe(0);
  });

  it("dequeuing an entry that was never queued is a no-op, not an error", async () => {
    await expect(dequeue("never-existed")).resolves.toBeUndefined();
  });

  it("records a failed attempt without dropping the entry", async () => {
    // A transient failure — still offline, a 5xx — must be retried, not lost.
    const item = entry();
    await enqueueQuickAdd(item);
    await markAttempt(item.idempotencyKey);
    await markAttempt(item.idempotencyKey);

    const [queued] = await listQueued();
    expect(queued.attempts).toBe(2);
    expect(await queueLength()).toBe(1);
  });

  it("marking an attempt on a missing entry does not create one", async () => {
    await markAttempt("never-queued");
    expect(await queueLength()).toBe(0);
  });

  it("re-queuing the same idempotency key updates rather than duplicates", async () => {
    // put() with a keyPath is an upsert — a resubmission from the UI (double
    // tap before the queue confirms) must not double the entry.
    const key = generateIdempotencyKey();
    await enqueueQuickAdd(entry({ idempotencyKey: key, amountMinor: 100 }));
    await enqueueQuickAdd(entry({ idempotencyKey: key, amountMinor: 200 }));

    const queued = await listQueued();
    expect(queued).toHaveLength(1);
    expect(queued[0].amountMinor).toBe(200);
  });

  it("clears everything", async () => {
    await enqueueQuickAdd(entry());
    await enqueueQuickAdd(entry());
    await clearQueue();
    expect(await queueLength()).toBe(0);
  });

  it("preserves optional fields like account and category", async () => {
    await enqueueQuickAdd(
      entry({ financialAccountId: "acct-1", categoryId: "cat-1", isIncome: true }),
    );
    const [queued] = await listQueued();
    expect(queued.financialAccountId).toBe("acct-1");
    expect(queued.categoryId).toBe("cat-1");
    expect(queued.isIncome).toBe(true);
  });
});
