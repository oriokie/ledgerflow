import { api } from "./client";

export type PolicyKind = "life" | "health" | "motor" | "home" | "liability" | "other";
export type PremiumFrequency = "monthly" | "quarterly" | "annual";

export interface InsurancePolicy {
  id: string;
  policy_id: string;
  name: string;
  kind: PolicyKind;
  insurer: string;
  currency: string;
  coverage_minor: number | null;
  deductible_minor: number | null;
  premium_minor: number;
  premium_frequency: PremiumFrequency;
  annual_premium_minor: number;
  monthly_premium_minor: number;
  renews_on: string | null;
  ends_on: string | null;
  covers_asset_id: string | null;
  covers_asset_name: string | null;
  asset_value_minor: number | null;
  coverage_gap_minor: number | null;
  covers_account_id: string | null;
  covers_account_name: string | null;
  bill_id: string | null;
  recurring_transaction_id: string | null;
  premium_in_cashflow: boolean;
  is_active: boolean;
  notes: string;
  underinsured: boolean;
}

export interface InsuranceSummary {
  currency: string;
  count: number;
  annual_premium_minor: number;
  underinsured_count: number;
  unlinked_count: number;
}

export const insuranceApi = {
  list: () => api.get<InsurancePolicy[]>("/insurance/"),
  summary: () => api.get<InsuranceSummary | null>("/insurance/summary/"),
  create: (payload: {
    name: string;
    kind: PolicyKind;
    currency: string;
    premium_minor: number;
    premium_frequency?: PremiumFrequency;
    insurer?: string;
    coverage_minor?: number | null;
    deductible_minor?: number | null;
    renews_on?: string | null;
    covers_asset_id?: string | null;
    notes?: string;
  }) => api.post<InsurancePolicy>("/insurance/", payload),
  retrieve: (id: string) => api.get<InsurancePolicy>(`/insurance/${id}/`),
  update: (
    id: string,
    payload: {
      name?: string;
      kind?: PolicyKind;
      insurer?: string;
      coverage_minor?: number | null;
      deductible_minor?: number | null;
      premium_minor?: number;
      premium_frequency?: PremiumFrequency;
      renews_on?: string | null;
      covers_asset_id?: string | null;
      is_active?: boolean;
      notes?: string;
    },
  ) => api.patch<InsurancePolicy>(`/insurance/${id}/`, payload),
  remove: (id: string) => api.delete<void>(`/insurance/${id}/`),
};
