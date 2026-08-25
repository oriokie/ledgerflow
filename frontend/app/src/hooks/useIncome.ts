import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { incomeApi, type IncomeSourcePayload } from "../api/income";
import { useAuth } from "../lib/AuthContext";

/** Every income query, so a mutation can invalidate the lot in one call. */
const ROOTS = ["income-sources", "income-summary", "income-source"] as const;

function useInvalidateIncome() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of ROOTS) queryClient.invalidateQueries({ queryKey: [key] });
    // The cash-flow projection reads income sources for payday marking and for
    // the expected amount of a variable source, so it goes stale too. Missing
    // this is how a user edits their salary and watches the calendar keep
    // drawing the old one.
    queryClient.invalidateQueries({ queryKey: ["cashflow"] });
  };
}

export function useIncomeSources() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["income-sources", activeWorkspace?.tenant.id],
    queryFn: () => incomeApi.listSources(),
    enabled: !!activeWorkspace,
  });
}

export function useIncomeSource(sourceId: string | undefined) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["income-source", sourceId],
    queryFn: () => incomeApi.getSource(sourceId!),
    enabled: !!activeWorkspace && !!sourceId,
  });
}

/**
 * The household's income position.
 *
 * Resolves to `null` — not an error, not a zeroed object — when no income has
 * been recorded. Callers must render that absence as "not told us yet" rather
 * than as "earns nothing".
 */
export function useIncomeSummary() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["income-summary", activeWorkspace?.tenant.id],
    queryFn: () => incomeApi.summary(),
    enabled: !!activeWorkspace,
  });
}

export function useCreateIncomeSource() {
  const invalidate = useInvalidateIncome();
  return useMutation({
    mutationFn: (payload: IncomeSourcePayload) => incomeApi.createSource(payload),
    onSuccess: invalidate,
  });
}

export function useUpdateIncomeSource() {
  const invalidate = useInvalidateIncome();
  return useMutation({
    mutationFn: ({
      sourceId,
      payload,
    }: {
      sourceId: string;
      payload: Partial<Omit<IncomeSourcePayload, "currency">>;
    }) => incomeApi.updateSource(sourceId, payload),
    onSuccess: invalidate,
  });
}

export function useDeleteIncomeSource() {
  const invalidate = useInvalidateIncome();
  return useMutation({
    mutationFn: (sourceId: string) => incomeApi.deleteSource(sourceId),
    onSuccess: invalidate,
  });
}

export function useAddDeduction() {
  const invalidate = useInvalidateIncome();
  return useMutation({
    mutationFn: ({
      sourceId,
      ...payload
    }: Parameters<typeof incomeApi.addDeduction>[1] & { sourceId: string }) =>
      incomeApi.addDeduction(sourceId, payload),
    onSuccess: invalidate,
  });
}

export function useRemoveDeduction() {
  const invalidate = useInvalidateIncome();
  return useMutation({
    mutationFn: ({ sourceId, deductionId }: { sourceId: string; deductionId: string }) =>
      incomeApi.removeDeduction(sourceId, deductionId),
    onSuccess: invalidate,
  });
}

export function useRecordReceipt() {
  const invalidate = useInvalidateIncome();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      sourceId,
      ...payload
    }: Parameters<typeof incomeApi.recordReceipt>[1] & { sourceId: string }) =>
      incomeApi.recordReceipt(sourceId, payload),
    onSuccess: () => {
      invalidate();
      // Receipts now post to the ledger — keep the activity feed in sync.
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["cashflow"] });
      queryClient.invalidateQueries({ queryKey: ["net-worth"] });
    },
  });
}
