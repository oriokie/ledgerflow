import { api } from "./client";
import type { LedgerAccount } from "./types";

/** The raw double-entry layer — a power-user/audit surface. Read-only in the
 * UI: postings happen through the finance domain, never directly here. */
export const ledgerApi = {
  listAccounts: () => api.get<LedgerAccount[]>("/ledger/accounts/"),
};
