import { api } from "./client";

export type ReceivableKind = "personal" | "invoice" | "reimbursement" | "deposit" | "other";
export type ReceivableStatus = "outstanding" | "settled" | "written_off";

export interface Receivable {
  id: string;
  receivable_id: string;
  counterparty: string;
  kind: ReceivableKind;
  description: string;
  currency: string;

  /** What was originally owed. Never reduced by repayments. */
  principal_minor: number;
  repaid_minor: number;
  outstanding_minor: number;

  lent_on: string;
  due_on: string | null;
  status: ReceivableStatus;

  /**
   * Negative while still in the future, positive once late, null when no date
   * was ever agreed. Null rather than 0 so "no deadline" is never rendered as
   * "due today".
   */
  days_overdue: number | null;
  /** How long the money has been out, whatever was agreed. For an informal
   * loan with no due date this is the figure that actually matters. */
  days_outstanding: number;

  repayment_count: number;
  last_received_on: string | null;
}

export interface RepaymentRow {
  id: string;
  received_on: string;
  amount_minor: number;
  memo: string;
}

export interface ReceivableDetail extends Receivable {
  repayments: RepaymentRow[];
}

export interface ReceivableSummary {
  currency: string;
  outstanding_minor: number;
  overdue_minor: number;
  settled_minor: number;
  written_off_minor: number;
  count: number;
  overdue_count: number;
  largest_counterparty: string | null;
  largest_minor: number;
}

export interface ReceivablePayload {
  counterparty: string;
  kind?: ReceivableKind;
  description?: string;
  currency: string;
  principal_minor: number;
  lent_on: string;
  due_on?: string | null;
  source_account_id?: string;
  notes?: string;
}

export const receivablesApi = {
  list: () => api.get<Receivable[]>("/receivables/"),

  get: (id: string) => api.get<ReceivableDetail>(`/receivables/${id}/`),

  /**
   * The endpoint answers 204 when nothing has ever been recorded, because a
   * body of zeros would assert the household is owed nothing. `api.get`
   * surfaces that as `null`, and callers must render the absence.
   */
  summary: () => api.get<ReceivableSummary | null>("/receivables/summary/"),

  create: (payload: ReceivablePayload) => api.post<Receivable>("/receivables/", payload),

  /** `currency` is absent by design — every repayment recorded is denominated
   * in it, so changing it would reinterpret history rather than correct it. */
  update: (id: string, payload: Partial<Omit<ReceivablePayload, "currency">>) =>
    api.patch<Receivable>(`/receivables/${id}/`, payload),

  remove: (id: string) => api.delete<void>(`/receivables/${id}/`),

  recordRepayment: (
    id: string,
    payload: { amount_minor: number; received_on: string; memo?: string },
  ) => api.post<Receivable>(`/receivables/${id}/repayments/`, payload),

  writeOff: (id: string) => api.post<Receivable>(`/receivables/${id}/write-off/`, {}),
};
