import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { quickAddApi } from "../api/finance";
import { drainQueueNow, onQuickAddSynced } from "../lib/pwa";
import {
  enqueueQuickAdd,
  generateIdempotencyKey,
  queueLength,
  type QueuedQuickAdd,
} from "../lib/offlineQueue";

export interface QuickAddInput {
  amountMinor: number;
  merchant: string;
  isIncome?: boolean;
  financialAccountId?: string;
  categoryId?: string;
  occurredAt?: string;
}

/**
 * Submit a Quick Add entry, online or offline, without the caller having to
 * know which.
 *
 * Every submission carries a client-generated idempotency key from the start
 * — including ones that succeed immediately online — so the *same* code path
 * handles a normal submission and a replay after a lost connection. There is
 * no special "offline mode" branch in the posting logic, only in whether the
 * request is attempted now or queued for later.
 *
 * On a genuine network failure (not a validation error — see below) the entry
 * is queued in IndexedDB and a sync is requested, so the user sees "saved,
 * will send" rather than losing what they just typed. On a real validation
 * failure (bad category, zero amount) the error surfaces immediately instead
 * of queueing something the server has already told us is wrong and will
 * tell us again identically the moment connectivity returns.
 */
export function useQuickAdd() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (input: QuickAddInput) => {
      const idempotencyKey = generateIdempotencyKey();
      try {
        return {
          queued: false as const,
          result: await quickAddApi.submit({ ...input, idempotencyKey }),
        };
      } catch (error) {
        if (isNetworkFailure(error)) {
          await enqueueQuickAdd({
            idempotencyKey,
            amountMinor: input.amountMinor,
            merchant: input.merchant,
            isIncome: input.isIncome ?? false,
            financialAccountId: input.financialAccountId,
            categoryId: input.categoryId,
            occurredAt: input.occurredAt ?? new Date().toISOString(),
          });
          void drainQueueNow(); // attempt immediately in case the network is actually back
          return { queued: true as const, result: null };
        }
        throw error;
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
    },
  });
}

/**
 * Distinguishes "the network is unreachable" from "the server answered with
 * an error". Only the former is safe to queue and retry blind — replaying a
 * 400 (bad category, non-positive amount) would just fail again identically,
 * and silently swallowing it into "saved offline" would hide a real mistake
 * from the person who made it.
 */
function isNetworkFailure(error: unknown): boolean {
  return error instanceof TypeError && /fetch|network/i.test(error.message);
}

/** Live count of what's waiting in the offline queue, refreshed whenever an
 * entry syncs — for a small badge/indicator, not a full queue viewer. */
export function usePendingQuickAddCount() {
  const [count, setCount] = useState(0);

  const refresh = useCallback(() => {
    void queueLength().then(setCount);
  }, []);

  useEffect(() => {
    refresh();
    const unsubscribe = onQuickAddSynced(() => refresh());
    window.addEventListener("online", refresh);
    return () => {
      unsubscribe();
      window.removeEventListener("online", refresh);
    };
  }, [refresh]);

  return count;
}

export type { QueuedQuickAdd };
