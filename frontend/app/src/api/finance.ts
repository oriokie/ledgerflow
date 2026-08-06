import { api, getBlob, postForm } from "./client";
import type {
  AccountUpdate,
  CashflowCalendar,
  CashflowCalendarDay,
  CashflowStatementData,
  NetWorthBase,
  Bill,
  CashFlowByCurrency,
  Category,
  CategoryBreakdownRow,
  CategoryTrendPoint,
  FinancialAccount,
  NetWorthByCurrency,
  Paginated,
  Payee,
  Transaction,
} from "./types";

/** What a statement contains, before anything is written. */
export interface MpesaPreview {
  customer_name: string;
  mobile_number: string;
  period_start: string;
  period_end: string;
  rows_found: number;
  paid_in_minor: number;
  withdrawn_minor: number;
  /** null when the statement printed no totals to check against — an honest
   *  "cannot tell", which the UI must not render as a tick. */
  reconciles: boolean | null;
  discrepancy: string;
  by_kind: Record<string, { count: number; total_minor: number }>;
  /** Rows per calendar day (YYYY-MM-DD), so a chosen window can be counted
   *  without shipping every row to the client. */
  by_day: Record<string, number>;
  first_seen: string | null;
  last_seen: string | null;
}

export interface MpesaImportResult {
  imported: number;
  skipped_duplicate: number;
  errors: { receipt: string; occurred_at: string; error: string }[];
  notices: string[];
  rows_found: number;
  /** How many of rows_found fell inside the chosen window. */
  rows_in_range: number;
  from_date: string;
  to_date: string;
  statement_period: string;
  reconciles: boolean | null;
  discrepancy: string;
  overdraft_advanced_minor: number;
  overdraft_repaid_minor: number;
  charges_minor: number;
  payees_created: number;
  auto_categorised: number;
}

export interface TransactionFilters {
  account_id?: string;
  category_id?: string;
  payee_id?: string;
  tag_id?: string;
  status?: string;
  type?: "income" | "expense" | "transfer";
  start?: string;
  end?: string;
  min_amount_minor?: number;
  max_amount_minor?: number;
  search?: string;
  needs_review?: boolean;
  cursor?: string;
  [key: string]: string | number | boolean | undefined;
}

function qs(params: Record<string, unknown>): string {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") usp.set(key, String(value));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export const financeApi = {
  listAccounts: () => api.get<FinancialAccount[]>("/finance/accounts/"),
  createAccount: (payload: {
    name: string;
    account_type: string;
    currency: string;
    mask?: string;
    color?: string;
    icon?: string;
    notes?: string;
    /** Positive magnitude in the account's natural direction: what you hold for
     * an asset, what you owe for a liability. The server derives the ledger
     * direction from account_type, so callers never reason about signs. */
    opening_balance_minor?: number;
    opening_balance_at?: string | null;
    include_in_net_worth?: boolean;
    include_in_budgets?: boolean;
  }) => api.post<FinancialAccount>("/finance/accounts/", payload),

  updateAccount: (accountId: string, payload: AccountUpdate) =>
    api.patch<FinancialAccount>(`/finance/accounts/${accountId}/`, payload),

  /** Archives rather than deletes: ledger history is immutable and stays. */
  archiveAccount: (accountId: string) =>
    api.delete<FinancialAccount>(`/finance/accounts/${accountId}/`),

  unarchiveAccount: (accountId: string) =>
    api.post<FinancialAccount>(`/finance/accounts/${accountId}/unarchive/`, {}),

  /** Day-by-day projected liquid balance. Returns null when the workspace has
   * no liquid account — the API answers 204 rather than an empty calendar,
   * because a zero balance would be a claim rather than an absence. */
  cashflowCalendar: (params: { start?: string; days?: number; currency?: string } = {}) =>
    api.get<CashflowCalendar | null>(
      `/finance/cashflow-calendar/${qs({ ...params })}`,
    ),

  cashflowDay: (day: string) => api.get<CashflowCalendarDay>(`/finance/cashflow-calendar/${day}/`),

  listCategories: () => api.get<Category[]>("/finance/categories/"),
  createCategory: (payload: { name: string; kind: string; currency: string; parent?: string }) =>
    api.post<Category>("/finance/categories/", payload),

  listPayees: () => api.get<Payee[]>("/finance/payees/"),

  listTransactions: (filters: TransactionFilters = {}) =>
    api.get<Paginated<Transaction>>(`/finance/transactions/${qs(filters)}`),

  createTransaction: (payload: {
    type: "income" | "expense";
    financial_account_id: string;
    category_id: string;
    amount_minor: number;
    occurred_at: string;
    memo?: string;
    payee_id?: string;
  }) => api.post<Transaction>("/finance/transactions/", payload),

  createTransfer: (payload: {
    from_account_id: string;
    to_account_id: string;
    amount_minor: number;
    occurred_at: string;
    memo?: string;
  }) => api.post<{ debit: Transaction; credit: Transaction }>("/finance/transfers/", payload),

  splitTransaction: (
    txnId: string,
    parts: { category_id: string; amount_minor: number; memo?: string }[],
  ) => api.post<Transaction[]>(`/finance/transactions/${txnId}/split/`, { parts }),

  bulkTransactions: (payload: { action: "categorize" | "void"; ids: string[]; category_id?: string | null }) =>
    api.post<BulkActionResult>("/finance/transactions/bulk/", payload),
  voidTransaction: (txnId: string) => api.post<void>(`/finance/transactions/${txnId}/void/`),

  exportTransactionsUrl: (filters: TransactionFilters = {}) =>
    `${import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1"}/finance/transactions/export/${qs(filters)}`,

  importTransactionsCsv: (accountId: string, content: string, defaultCategoryId?: string) =>
    api.post<{ imported: number; skipped_duplicate: number; errors: { line: number; error: string }[] }>(
      "/finance/transactions/import/",
      { account_id: accountId, content, default_category_id: defaultCategoryId },
    ),

  /** Parse an M-Pesa statement and describe it, writing nothing.
   *
   *  The read-only half of a deliberately two-step flow: a statement is three
   *  months of somebody's life and the import is hundreds of rows, so the
   *  reconciliation check has to be visible before it happens, not after. */
  previewMpesaStatement: (file: File, password: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("password", password);
    return postForm<MpesaPreview>("/finance/transactions/import/mpesa/?preview=1", form);
  },

  importMpesaStatement: (
    accountId: string,
    file: File,
    password: string,
    opts: { fromDate?: string; toDate?: string; trackOverdraftAsDebt?: boolean } = {},
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("password", password);
    form.append("account_id", accountId);
    form.append("track_overdraft_as_debt", String(opts.trackOverdraftAsDebt ?? true));
    // Sent only when set. A blank field means "no bound", which is a different
    // statement from any particular date.
    if (opts.fromDate) form.append("from_date", opts.fromDate);
    if (opts.toDate) form.append("to_date", opts.toDate);
    return postForm<MpesaImportResult>("/finance/transactions/import/mpesa/", form);
  },

  netWorth: () => api.get<NetWorthByCurrency[]>("/finance/net-worth/"),
  netWorthBase: () => api.get<NetWorthBase>("/finance/net-worth/base/"),
  cashflowStatement: (months = 6) =>
    api.get<CashflowStatementData>(`/finance/cashflow-statement/?months=${months}`),
  cashFlow: (start: string, end: string) =>
    api.get<CashFlowByCurrency[]>(`/finance/cash-flow/${qs({ start, end })}`),
  categoryBreakdown: (start: string, end: string, type: "income" | "expense" = "expense") =>
    api.get<CategoryBreakdownRow[]>(`/finance/category-breakdown/${qs({ start, end, type })}`),
  categoryTrend: (categoryId: string, months = 6, type: "income" | "expense" = "expense") =>
    api.get<CategoryTrendPoint[]>(`/finance/category-trend/${qs({ category_id: categoryId, months, type })}`),

  /** How many transactions are flagged for review. A count, not a page: the
   * list endpoint is cursor-paginated and cursor pagination has no total. */
  reviewCount: () => api.get<{ count: number }>("/finance/transactions/review-count/"),

  listBills: (params: { status?: string; upcoming?: number } = {}) =>
    api.get<Bill[]>(`/finance/bills/${qs(params)}`),
  createBill: (payload: {
    name: string;
    amount_minor: number;
    currency: string;
    due_on: string;
    payee_id?: string;
    category_id?: string;
    recurrence_frequency?: string;
    autopay_account_id?: string;
    notes?: string;
  }) => api.post<Bill>("/finance/bills/", payload),
  payBill: (billId: string, payload: { from_account_id?: string; amount_minor?: number } = {}) =>
    api.post<{ bill: Bill; settling_transaction_id: string | null }>(
      `/finance/bills/${billId}/pay/`,
      payload,
    ),
  cancelBill: (billId: string) => api.delete<void>(`/finance/bills/${billId}/`),
};

// ---------------------------------------------------------------- extended
import type {
  RecurringTransaction,
  Statement,
  Tag,
  Wallet,
} from "./types";

export const walletsApi = {
  list: () => api.get<Wallet[]>("/finance/wallets/"),
  create: (payload: { name: string; icon?: string; color?: string; is_default?: boolean }) =>
    api.post<Wallet>("/finance/wallets/", payload),
  assignAccount: (financial_account_id: string, wallet_id: string | null) =>
    api.post("/finance/wallets/assign-account/", { financial_account_id, wallet_id }),
};

export const financeExtendedApi = {
  updateCategory: (
    categoryId: string,
    payload: { name?: string; color?: string; icon?: string },
  ) => api.patch(`/finance/categories/${categoryId}/`, payload),

  deleteCategory: (categoryId: string) => api.delete<void>(`/finance/categories/${categoryId}/`),

  accountStatement: (accountId: string, start: string, end: string) =>
    api.get<Statement>(`/finance/accounts/${accountId}/statement/${qs({ start, end })}`),

  updateTransaction: (
    txnId: string,
    payload: { category_id?: string | null; payee_id?: string | null; memo?: string },
  ) => api.patch(`/finance/transactions/${txnId}/`, payload),

  /** The blank CSV import template, as text. Served by the same module that
   *  parses uploads, so the columns handed out cannot drift from the columns
   *  accepted. */
  importTemplate: () => getBlob("/finance/transactions/import/"),

  listRecurring: () => api.get<RecurringTransaction[]>("/finance/recurring/"),
  createRecurring: (payload: {
    txn_type: string;
    financial_account_id: string;
    counter_account_id?: string;
    category_id?: string;
    amount_minor: number;
    currency: string;
    frequency: string;
    interval?: number;
    starts_on: string;
    ends_on?: string;
    memo?: string;
  }) => api.post<RecurringTransaction>("/finance/recurring/", payload),

  /**
   * Pause/resume, or edit the plan going forward.
   *
   * `txn_type`, `currency` and `financial_account_id` are absent on purpose:
   * every occurrence the template already posted carries them, so changing one
   * would reinterpret history rather than correct the plan. The server refuses
   * them too — this type just stops the client asking.
   */
  updateRecurring: (
    recId: string,
    payload: {
      is_active?: boolean;
      amount_minor?: number;
      category_id?: string | null;
      counter_account_id?: string | null;
      frequency?: string;
      interval?: number;
      starts_on?: string;
      ends_on?: string | null;
      max_occurrences?: number | null;
      memo?: string;
    },
  ) => api.patch<RecurringTransaction>(`/finance/recurring/${recId}/`, payload),

  cancelRecurring: (recId: string) => api.delete<void>(`/finance/recurring/${recId}/`),

  listTags: () => api.get<Tag[]>("/finance/tags/"),
  createTag: (payload: { name: string; color?: string }) => api.post<Tag>("/finance/tags/", payload),
  setTransactionTags: (txnId: string, tag_ids: string[]) =>
    api.put<Tag[]>(`/finance/transactions/${txnId}/tags/`, { tag_ids }),

  createPayee: (payload: { name: string; default_category_id?: string }) =>
    api.post("/finance/payees/", payload),

  /** Export needs the Bearer token, so a plain <a href> can't carry it —
   * fetch with auth, then hand the blob to the browser as a download. */
  downloadExport: async (filters: TransactionFilters = {}) => {
    const { tokenStore, tenantStore } = await import("./tokenStore");
    const url = `${BASE_URL_EXPORT}/finance/transactions/export/${qs(filters)}`;
    const res = await fetch(url, {
      headers: {
        Authorization: `Bearer ${tokenStore.getAccess() ?? ""}`,
        "X-Tenant-ID": tenantStore.getActive() ?? "",
      },
    });
    if (!res.ok) throw new Error("Export failed");
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "transactions.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  },
};

const BASE_URL_EXPORT = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

export interface AttachmentInfo {
  id: string;
  transaction_id: string | null;
  content_type: string;
  byte_size: number;
  status: string;
  checksum: string;
  /** API path to fetch the stored file — present only once uploaded. */
  download_url: string | null;
}

export interface BulkActionResult {
  requested: number;
  updated: number;
  failed: { id: string; error: string }[];
}

export const attachmentsApi = {
  listForTransaction: (txnId: string) =>
    api.get<AttachmentInfo[]>(`/finance/transactions/${txnId}/attachments/`),
  /** Step 1: register the upload; `upload_url` is null when the storage
   * backend can't presign (local dev) — the UI says so instead of showing a
   * broken button. */
  requestUpload: (txnId: string, payload: { filename: string; content_type: string; byte_size: number }) =>
    api.post<AttachmentInfo & { upload_url: string | null }>(
      `/finance/transactions/${txnId}/attachments/request-upload/`,
      payload,
    ),
  confirm: (attachmentId: string, checksum = "") =>
    api.post<AttachmentInfo>(`/finance/attachments/${attachmentId}/confirm/`, { checksum }),
  /** Direct server-side upload — used when the storage backend can't presign
   * (local dev). Streams the bytes through our API to object storage. */
  directUpload: (attachmentId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return postForm<AttachmentInfo>(`/finance/attachments/${attachmentId}/upload/`, form);
  },
  /** Fetch a stored receipt as a Blob (auth-scoped). */
  download: (attachmentId: string) => getBlob(`/finance/attachments/${attachmentId}/download/`),
};

export const quickAddApi = {
  submit: (payload: {
    amountMinor: number;
    merchant: string;
    isIncome?: boolean;
    financialAccountId?: string | null;
    categoryId?: string | null;
    occurredAt?: string;
    /** Resent unchanged on retry — what makes a queued offline submission
     * safe to replay without risking a double post. */
    idempotencyKey?: string;
  }) =>
    api.post<import("./types").QuickAddResult>("/finance/quick-add/", {
      amount_minor: payload.amountMinor,
      merchant: payload.merchant,
      is_income: payload.isIncome ?? false,
      financial_account_id: payload.financialAccountId ?? null,
      category_id: payload.categoryId ?? null,
      occurred_at: payload.occurredAt ?? null,
      idempotency_key: payload.idempotencyKey ?? null,
    }),

  recentMerchants: () => api.get<string[]>("/finance/quick-add/recent-merchants/"),
};
