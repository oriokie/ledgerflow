import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { financeApi, type TransactionFilters } from "../api/finance";
import type { Paginated, Transaction } from "../api/types";
import { useAuth } from "../lib/AuthContext";

function tenantKey(id: string | undefined, ...rest: unknown[]) {
  return [id, ...rest];
}

export function useAccounts(includeArchived = false) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["accounts", ...tenantKey(activeWorkspace?.tenant.id), includeArchived],
    queryFn: () => financeApi.listAccounts({ includeArchived }),
    enabled: !!activeWorkspace,
  });
}

export function useCreateAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: financeApi.createAccount,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useUpdateAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId, payload }: { accountId: string; payload: Parameters<typeof financeApi.updateAccount>[1] }) =>
      financeApi.updateAccount(accountId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useArchiveAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) => financeApi.archiveAccount(accountId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useUnarchiveAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) => financeApi.unarchiveAccount(accountId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useDeleteAccount() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) => financeApi.purgeAccount(accountId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useCategories() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["categories", ...tenantKey(activeWorkspace?.tenant.id)],
    queryFn: () => financeApi.listCategories(),
    enabled: !!activeWorkspace,
    staleTime: 5 * 60_000, // categories change rarely
  });
}

export function useCreateCategory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: financeApi.createCategory,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["categories"] }),
  });
}

export function useUpdateCategory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      categoryId,
      payload,
    }: {
      categoryId: string;
      payload: { name?: string; color?: string; icon?: string; parent_id?: string | null };
    }) => financeExtendedApi.updateCategory(categoryId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["categories"] }),
  });
}

export function useDeleteCategory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (categoryId: string) => financeExtendedApi.deleteCategory(categoryId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      queryClient.invalidateQueries({ queryKey: ["category-breakdown"] });
    },
  });
}

export function usePayees() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["payees", ...tenantKey(activeWorkspace?.tenant.id)],
    queryFn: () => financeApi.listPayees(),
    enabled: !!activeWorkspace,
  });
}

export function useTransactions(filters: TransactionFilters, enabled = true) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["transactions", activeWorkspace?.tenant.id, filters],
    queryFn: () => financeApi.listTransactions(filters),
    enabled: !!activeWorkspace && enabled,
  });
}

function invalidateMoneyViews(queryClient: ReturnType<typeof useQueryClient>) {
  // A posting invalidates everything derived from the ledger: balances,
  // lists, and every analytics view built on top of it.
  queryClient.invalidateQueries({ queryKey: ["accounts"] });
  queryClient.invalidateQueries({ queryKey: ["transactions"] });
  queryClient.invalidateQueries({ queryKey: ["net-worth"] });
  queryClient.invalidateQueries({ queryKey: ["cash-flow"] });
  queryClient.invalidateQueries({ queryKey: ["category-breakdown"] });
  queryClient.invalidateQueries({ queryKey: ["budget-status"] });
  queryClient.invalidateQueries({ queryKey: ["health-score"] });
  queryClient.invalidateQueries({ queryKey: ["recommendations"] });
  queryClient.invalidateQueries({ queryKey: ["anomalies"] });
  queryClient.invalidateQueries({ queryKey: ["net-worth-history"] });
  queryClient.invalidateQueries({ queryKey: ["spending-trend"] });
}

export function useCreateTransaction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: financeApi.createTransaction,
    onSuccess: () => invalidateMoneyViews(queryClient),
  });
}

export function useCreateTransfer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: financeApi.createTransfer,
    onSuccess: () => invalidateMoneyViews(queryClient),
  });
}

export function useSplitTransaction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ txnId, parts }: { txnId: string; parts: { category_id: string; amount_minor: number; memo?: string }[] }) =>
      financeApi.splitTransaction(txnId, parts),
    onSuccess: () => invalidateMoneyViews(queryClient),
  });
}

export function useReclassifyTransfer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ txnId, counterAccountId }: { txnId: string; counterAccountId: string }) =>
      financeApi.reclassifyAsTransfer(txnId, counterAccountId),
    onSuccess: () => invalidateMoneyViews(queryClient),
  });
}

export function useVoidTransaction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: financeApi.voidTransaction,
    onSuccess: () => invalidateMoneyViews(queryClient),
  });
}

export function useImportTransactionsCsv() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId, content, defaultCategoryId }: { accountId: string; content: string; defaultCategoryId?: string }) =>
      financeApi.importTransactionsCsv(accountId, content, defaultCategoryId),
    onSuccess: () => invalidateMoneyViews(queryClient),
  });
}

/** Parse-and-describe only. No mutation, so no cache invalidation — nothing
 *  has changed yet, and that is the entire point of the step. */
export function usePreviewMpesaStatement() {
  return useMutation({
    mutationFn: ({ file, password }: { file: File; password: string }) =>
      financeApi.previewMpesaStatement(file, password),
  });
}

export function useImportMpesaStatement() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      file,
      password,
      fromDate,
      toDate,
      trackOverdraftAsDebt,
    }: {
      accountId: string;
      file: File;
      password: string;
      fromDate?: string;
      toDate?: string;
      trackOverdraftAsDebt?: boolean;
    }) =>
      financeApi.importMpesaStatement(accountId, file, password, {
        fromDate,
        toDate,
        trackOverdraftAsDebt,
      }),
    onSuccess: () => invalidateMoneyViews(queryClient),
  });
}

export function useNetWorth() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["net-worth", activeWorkspace?.tenant.id],
    queryFn: () => financeApi.netWorth(),
    enabled: !!activeWorkspace,
  });
}

export function useCashFlow(start: string, end: string) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["cash-flow", activeWorkspace?.tenant.id, start, end],
    queryFn: () => financeApi.cashFlow(start, end),
    enabled: !!activeWorkspace,
  });
}

export function useCategoryBreakdown(start: string, end: string, type: "income" | "expense" = "expense") {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["category-breakdown", activeWorkspace?.tenant.id, start, end, type],
    queryFn: () => financeApi.categoryBreakdown(start, end, type),
    enabled: !!activeWorkspace,
  });
}

export function useCategoryTrend(
  categoryId: string | undefined,
  months = 6,
  type: "income" | "expense" = "expense",
) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["category-trend", activeWorkspace?.tenant.id, categoryId, months, type],
    queryFn: () => financeApi.categoryTrend(categoryId!, months, type),
    enabled: !!activeWorkspace && !!categoryId,
  });
}

export function useBills(params: { status?: string; upcoming?: number } = {}) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["bills", activeWorkspace?.tenant.id, params],
    queryFn: () => financeApi.listBills(params),
    enabled: !!activeWorkspace,
  });
}

export function useCreateBill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: financeApi.createBill,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["bills"] }),
  });
}

export function usePayBill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ billId, payload }: { billId: string; payload?: { from_account_id?: string; amount_minor?: number } }) =>
      financeApi.payBill(billId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["bills"] });
      invalidateMoneyViews(queryClient);
    },
  });
}

export function useCancelBill() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (billId: string) => financeApi.cancelBill(billId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["bills"] }),
  });
}

// ---------------------------------------------------------------- extended
import { attachmentsApi, financeExtendedApi, walletsApi } from "../api/finance";

export function useWallets() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["wallets", activeWorkspace?.tenant.id],
    queryFn: () => walletsApi.list(),
    enabled: !!activeWorkspace,
  });
}

export function useCreateWallet() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: walletsApi.create,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["wallets"] }),
  });
}

export function useAssignAccountToWallet() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ accountId, walletId }: { accountId: string; walletId: string | null }) =>
      walletsApi.assignAccount(accountId, walletId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wallets"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
    },
  });
}

export function useAccountStatement(accountId: string | null, start: string, end: string) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["statement", accountId, start, end],
    queryFn: () => financeExtendedApi.accountStatement(accountId!, start, end),
    enabled: !!activeWorkspace && !!accountId,
  });
}

/**
 * Editing a transaction — overwhelmingly, categorizing one from the inline
 * dropdown in the ledger — is the single most repeated action in the product.
 *
 * It is therefore the one mutation that most needs to feel instantaneous. The
 * previous implementation round-tripped to the server and then invalidated ten
 * query families, so choosing a category made the whole ledger flicker and the
 * dropdown snap back until the refetch landed. On a long list that reads as a
 * stall on every single categorization.
 *
 * Now the change is applied to the cache immediately and reconciled afterwards:
 *
 *   onMutate   — snapshot every transaction page, patch the row in place, and
 *                return the snapshot as rollback context.
 *   onError    — restore the snapshot exactly. A failed edit must never leave a
 *                wrong category sitting on screen looking saved; this is money
 *                software and a silent lie is worse than a slow save.
 *   onSettled  — invalidate the derived views (budgets, breakdowns, health) so
 *                the numbers computed from this row catch up.
 *
 * Only the row's own list is patched optimistically. Everything derived from it
 * is left to the refetch, because guessing at an aggregate is how a UI ends up
 * showing a total that never existed.
 */
export function useUpdateTransaction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      txnId,
      payload,
    }: {
      txnId: string;
      payload: { category_id?: string | null; payee_id?: string | null; memo?: string };
    }) => financeExtendedApi.updateTransaction(txnId, payload),

    onMutate: async ({ txnId, payload }) => {
      // Stop in-flight refetches from clobbering the optimistic value.
      await queryClient.cancelQueries({ queryKey: ["transactions"] });
      const snapshot = queryClient.getQueriesData<Paginated<Transaction>>({ queryKey: ["transactions"] });

      for (const [key, page] of snapshot) {
        if (!page?.results) continue;
        queryClient.setQueryData<Paginated<Transaction>>(key, {
          ...page,
          results: page.results.map((t) => (t.id === txnId ? { ...t, ...payload } : t)),
        });
      }

      return { snapshot };
    },

    onError: (_err, _vars, context) => {
      for (const [key, page] of context?.snapshot ?? []) {
        queryClient.setQueryData(key, page);
      }
    },

    onSettled: () => invalidateMoneyViews(queryClient),
  });
}

export function useRecurring() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["recurring", activeWorkspace?.tenant.id],
    queryFn: () => financeExtendedApi.listRecurring(),
    enabled: !!activeWorkspace,
  });
}

export function useCreateRecurring() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: financeExtendedApi.createRecurring,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["recurring"] }),
  });
}
export function useSetRecurringActive() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ recId, active }: { recId: string; active: boolean }) =>
      financeExtendedApi.updateRecurring(recId, { is_active: active }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["recurring"] }),
  });
}
export function useUpdateRecurring() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      recId,
      ...payload
    }: { recId: string } & Parameters<typeof financeExtendedApi.updateRecurring>[1]) =>
      financeExtendedApi.updateRecurring(recId, payload),
    // An edited schedule changes what is projected to be posted, so the money
    // views have to be refetched alongside the list — not just the list.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["recurring"] }),
    onSettled: () => invalidateMoneyViews(queryClient),
  });
}
export function useCancelRecurring() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (recId: string) => financeExtendedApi.cancelRecurring(recId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["recurring"] }),
  });
}

export function useConfirmRecurring() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      recId,
      amount_minor,
      occurred_on,
    }: {
      recId: string;
      amount_minor?: number;
      occurred_on?: string;
    }) => financeExtendedApi.confirmRecurring(recId, { amount_minor, occurred_on }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["recurring"] });
      invalidateMoneyViews(queryClient);
    },
  });
}

export function useImportBillsXlsx() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => financeExtendedApi.importBillsXlsx(file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["bills"] }),
  });
}

export function useImportRecurringXlsx() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => financeExtendedApi.importRecurringXlsx(file),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["recurring"] }),
  });
}

export function useTags() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["tags", activeWorkspace?.tenant.id],
    queryFn: () => financeExtendedApi.listTags(),
    enabled: !!activeWorkspace,
    staleTime: 5 * 60_000,
  });
}

export function useCreateTag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: financeExtendedApi.createTag,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tags"] }),
  });
}

export function useSetTransactionTags() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ txnId, tagIds }: { txnId: string; tagIds: string[] }) =>
      financeExtendedApi.setTransactionTags(txnId, tagIds),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["transactions"] }),
  });
}

export function useCreatePayee() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: financeExtendedApi.createPayee,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["payees"] }),
  });
}

export function useTransactionAttachments(txnId: string | null) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["attachments", txnId],
    queryFn: () => attachmentsApi.listForTransaction(txnId!),
    enabled: !!activeWorkspace && !!txnId,
  });
}

// ---------------------------------------------------------------------------
// Bulk operations. Backed by a single server-side batch endpoint
// (POST /finance/transactions/bulk/) that categorizes/voids in one request and
// reports per-row failures, so N selected rows are one round-trip, not N.
// ---------------------------------------------------------------------------

export interface BulkResult {
  total: number;
  failed: number;
}

/** Apply one category to many transactions in a single request. */
export function useBulkUpdateTransactions() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ ids, payload }: { ids: string[]; payload: { category_id?: string | null } }) => {
      const res = await financeApi.bulkTransactions({ action: "categorize", ids, category_id: payload.category_id });
      return { total: res.requested, failed: res.failed.length } satisfies BulkResult;
    },
    onSuccess: () => invalidateMoneyViews(queryClient),
  });
}

/** Void many transactions in a single request. */
export function useBulkVoidTransactions() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ ids }: { ids: string[] }) => {
      const res = await financeApi.bulkTransactions({ action: "void", ids });
      return { total: res.requested, failed: res.failed.length } satisfies BulkResult;
    },
    onSuccess: () => invalidateMoneyViews(queryClient),
  });
}

/**
 * Receipt upload. Prefers the presigned direct-to-storage PUT (production S3,
 * keeping bytes off the app server); when the backend can't presign — local dev
 * or any non-S3 backend — it falls back to streaming the bytes through our own
 * upload endpoint. Either way the receipt ends up stored and downloadable.
 */
export function useUploadReceipt(txnId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const contentType = file.type || "application/octet-stream";
      const info = await attachmentsApi.requestUpload(txnId, {
        filename: file.name,
        content_type: contentType,
        byte_size: file.size,
      });
      if (info.upload_url) {
        const put = await fetch(info.upload_url, {
          method: "PUT",
          body: file,
          headers: { "Content-Type": contentType },
        });
        if (!put.ok) throw new Error("Upload failed — please try again.");
        return attachmentsApi.confirm(info.id, "");
      }
      // No presigning available: stream the bytes through our API to storage.
      return attachmentsApi.directUpload(info.id, file);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["attachments", txnId] }),
  });
}

export function useCashflowStatement(months = 6) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["cashflow-statement", activeWorkspace?.tenant.id, months],
    queryFn: () => financeApi.cashflowStatement(months),
    enabled: !!activeWorkspace,
  });
}

/** Transactions an import or a rule could not confidently place. */
export function useReviewCount(enabled = true) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["transactions", "review-count", activeWorkspace?.tenant.id],
    queryFn: () => financeApi.reviewCount(),
    enabled: !!activeWorkspace && enabled,
  });
}

export function useNetWorthBase() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["net-worth-base", activeWorkspace?.tenant.id],
    queryFn: () => financeApi.netWorthBase(),
    enabled: !!activeWorkspace,
  });
}

/**
 * Day-by-day projected liquid balance.
 *
 * Kept on a short stale time: the projection is derived from balances and
 * schedules that change during a session, and a stale overdraft warning is
 * worse than a slightly slower one.
 */
export function useCashflowCalendar(params: { start?: string; days?: number; currency?: string } = {}) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["cashflow-calendar", activeWorkspace?.tenant.id, params],
    queryFn: () => financeApi.cashflowCalendar(params),
    enabled: !!activeWorkspace,
    staleTime: 30_000,
  });
}
