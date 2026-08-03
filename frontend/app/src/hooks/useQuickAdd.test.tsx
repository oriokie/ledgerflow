import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { clearQueue, listQueued } from "../lib/offlineQueue";

const submit = vi.fn();
vi.mock("../api/finance", () => ({ quickAddApi: { submit: (...a: unknown[]) => submit(...a) } }));

const drainQueueNow = vi.fn();
vi.mock("../lib/pwa", () => ({
  drainQueueNow: (...a: unknown[]) => drainQueueNow(...a),
  onQuickAddSynced: () => () => {},
}));

import { useQuickAdd } from "./useQuickAdd";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(async () => {
  vi.clearAllMocks();
  await clearQueue();
});

describe("useQuickAdd", () => {
  it("posts directly when the network is reachable", async () => {
    submit.mockResolvedValue({ transaction_id: "t1", amount_minor: -1250 });
    const { result } = renderHook(() => useQuickAdd(), { wrapper });

    result.current.mutate({ amountMinor: 1250, merchant: "Corner Shop" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.queued).toBe(false);
    expect(await listQueued()).toHaveLength(0);
  });

  it("every submission carries an idempotency key, even the fast path", async () => {
    // The same code path handles a normal submission and a replay — there is
    // no separate "offline mode" branch in the posting logic itself.
    submit.mockResolvedValue({ transaction_id: "t1" });
    const { result } = renderHook(() => useQuickAdd(), { wrapper });

    result.current.mutate({ amountMinor: 1250, merchant: "Shop" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({ idempotencyKey: expect.stringMatching(/^quick-add:/) }),
    );
  });

  it("queues the entry on a genuine network failure rather than losing it", async () => {
    submit.mockRejectedValue(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => useQuickAdd(), { wrapper });

    result.current.mutate({ amountMinor: 1250, merchant: "Corner Shop" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.queued).toBe(true);
    const queued = await listQueued();
    expect(queued).toHaveLength(1);
    expect(queued[0].merchant).toBe("Corner Shop");
  });

  it("attempts an immediate drain after queueing, in case the network is actually back", async () => {
    submit.mockRejectedValue(new TypeError("NetworkError when attempting to fetch resource"));
    const { result } = renderHook(() => useQuickAdd(), { wrapper });

    result.current.mutate({ amountMinor: 500, merchant: "Shop" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(drainQueueNow).toHaveBeenCalled();
  });

  it("does not queue a real validation failure — that would just fail again identically", async () => {
    submit.mockRejectedValue(new ApiError(400, { detail: "Amount must be positive." }));
    const { result } = renderHook(() => useQuickAdd(), { wrapper });

    result.current.mutate({ amountMinor: 0, merchant: "Shop" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(await listQueued()).toHaveLength(0);
  });

  it("a session-expiry ApiError is surfaced, not silently queued", async () => {
    submit.mockRejectedValue(new ApiError(401, { detail: "Session expired." }));
    const { result } = renderHook(() => useQuickAdd(), { wrapper });

    result.current.mutate({ amountMinor: 500, merchant: "Shop" });
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(await listQueued()).toHaveLength(0);
  });
});
