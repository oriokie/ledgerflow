import { api } from "./client";

export type IncomeKind =
  | "employment"
  | "self_employment"
  | "business"
  | "rental"
  | "pension"
  | "benefits"
  | "investment"
  | "other";

export type Reliability = "fixed" | "variable" | "irregular";

export type IncomeFrequency =
  | "daily"
  | "weekly"
  | "fortnightly"
  | "semi_monthly"
  | "monthly"
  | "quarterly"
  | "annual"
  | "ad_hoc";

export type DeductionKind =
  | "tax"
  | "social_security"
  | "pension"
  | "health"
  | "loan"
  | "union"
  | "other";

export interface IncomeSource {
  id: string;
  name: string;
  kind: IncomeKind;
  payer: string;
  currency: string;
  frequency: IncomeFrequency;
  reliability: Reliability;
  is_active: boolean;
  starts_on: string;
  ends_on: string | null;
  is_current: boolean;

  /** What the user said one payment is worth. */
  stated_net_minor: number;
  stated_gross_minor: number | null;

  /** What payments have actually been worth. Null until there are enough. */
  observed_mean_minor: number | null;
  observed_stdev_minor: number | null;
  receipt_count: number;
  last_received_on: string | null;

  /** The figure to plan with — observed where it exists, stated otherwise. */
  expected_net_minor: number;
  expected_is_observed: boolean;

  /** Null for an ad-hoc cadence: there is no honest monthly equivalent. */
  monthly_net_minor: number | null;
  /** Null when a percentage deduction has no gross to resolve against. */
  deductions_minor: number | null;
  variance_pct: number | null;

  /**
   * True when this figure is a hope rather than a measurement — an irregular
   * source with no receipt history. The server sends it rather than letting
   * the client re-derive it, so certainty always travels with the number.
   */
  is_speculative: boolean;
}

export interface IncomeDeduction {
  id: string;
  kind: DeductionKind;
  label: string;
  amount_minor: number | null;
  /** Basis points: 2000 is 20%. */
  percent_bp: number | null;
}

export interface IncomeReceipt {
  id: string;
  occurred_on: string;
  net_minor: number;
  gross_minor: number | null;
  memo: string;
}

export interface IncomeSourceDetail extends IncomeSource {
  deductions: IncomeDeduction[];
  receipts: IncomeReceipt[];
}

export interface CommittedIncome {
  committed_minor: number;
  free_minor: number;
  committed_pct: number | null;
  /** The same ratio against only the income that is contractually promised. */
  committed_against_fixed_pct: number | null;
  bills_minor: number;
  debt_minimums_minor: number;
  recurring_expenses_minor: number;
}

export interface IncomeSummary {
  currency: string;
  monthly_net_minor: number;
  monthly_gross_minor: number | null;
  monthly_fixed_minor: number;
  monthly_variable_minor: number;
  monthly_deductions_minor: number | null;
  take_home_rate: number | null;
  concentration_pct: number | null;
  source_count: number;
  /** Sources with no cadence, so absent from the monthly total. */
  ad_hoc_count: number;
  speculative_count: number;
  committed: CommittedIncome | null;
}

export interface IncomeSourcePayload {
  name: string;
  kind?: IncomeKind;
  payer?: string;
  currency: string;
  net_minor: number;
  gross_minor?: number | null;
  /** Omit to let the server derive it from `kind`. */
  reliability?: Reliability;
  frequency?: IncomeFrequency;
  pay_day?: number | null;
  second_pay_day?: number | null;
  starts_on: string;
  ends_on?: string | null;
  deposit_account_id?: string;
  notes?: string;
}

export const incomeApi = {
  listSources: () => api.get<IncomeSource[]>("/income/sources/"),

  getSource: (sourceId: string) => api.get<IncomeSourceDetail>(`/income/sources/${sourceId}/`),

  /**
   * The endpoint answers 204 when no income is recorded, because a body of
   * zeros would assert the household earns nothing. `api.get` surfaces that as
   * `null`, and callers must render the absence rather than substituting 0.
   */
  summary: () => api.get<IncomeSummary | null>("/income/summary/"),

  createSource: (payload: IncomeSourcePayload) =>
    api.post<IncomeSource>("/income/sources/", payload),

  updateSource: (sourceId: string, payload: Partial<Omit<IncomeSourcePayload, "currency">>) =>
    api.patch<IncomeSource>(`/income/sources/${sourceId}/`, payload),

  deleteSource: (sourceId: string) => api.delete<void>(`/income/sources/${sourceId}/`),

  addDeduction: (
    sourceId: string,
    payload: { kind: DeductionKind; label?: string; amount_minor?: number; percent_bp?: number },
  ) => api.post<IncomeDeduction>(`/income/sources/${sourceId}/deductions/`, payload),

  removeDeduction: (sourceId: string, deductionId: string) =>
    api.delete<void>(`/income/sources/${sourceId}/deductions/${deductionId}/`),

  recordReceipt: (
    sourceId: string,
    payload: { occurred_on: string; net_minor: number; gross_minor?: number; memo?: string },
  ) => api.post<IncomeReceipt>(`/income/sources/${sourceId}/receipts/`, payload),
};
