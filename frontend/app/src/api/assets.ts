import { api } from "./client";

export type AssetKind = "property" | "land" | "vehicle" | "valuable" | "business" | "other";
export type ValuationSource = "purchase" | "owner" | "professional" | "market";

export interface TangibleAsset {
  id: string;
  asset_id: string;
  name: string;
  kind: AssetKind;
  currency: string;
  description: string;
  acquired_on: string | null;
  acquisition_cost_minor: number | null;
  value_minor: number | null;
  valued_on: string | null;
  valuation_source: ValuationSource | null;
  valuation_count: number;
  secured_debt_account_id: string | null;
  secured_debt_name: string | null;
  debt_minor: number;
  include_in_net_worth: boolean;
  equity_minor: number | null;
  loan_to_value_pct: number | null;
  gain_minor: number | null;
}

export interface AssetValuation {
  id: string;
  as_of: string;
  value_minor: number;
  source: ValuationSource;
  notes: string;
}

export interface AssetDetail extends TangibleAsset {
  valuations: AssetValuation[];
}

export interface AssetSummary {
  currency: string;
  value_minor: number;
  debt_minor: number;
  equity_minor: number;
  count: number;
  unvalued_count: number;
}

export const assetsApi = {
  list: () => api.get<TangibleAsset[]>("/assets/"),
  summary: () => api.get<AssetSummary | null>("/assets/summary/"),
  create: (payload: {
    name: string;
    kind: AssetKind;
    currency: string;
    description?: string;
    acquired_on?: string | null;
    acquisition_cost_minor?: number | null;
    secured_by_debt_id?: string | null;
    include_in_net_worth?: boolean;
    notes?: string;
    initial_value_minor?: number | null;
  }) => api.post<TangibleAsset>("/assets/", payload),
  retrieve: (id: string) => api.get<AssetDetail>(`/assets/${id}/`),
  update: (
    id: string,
    payload: {
      name?: string;
      kind?: AssetKind;
      description?: string;
      acquired_on?: string | null;
      acquisition_cost_minor?: number | null;
      secured_by_debt_id?: string | null;
      include_in_net_worth?: boolean;
      notes?: string;
    },
  ) => api.patch<TangibleAsset>(`/assets/${id}/`, payload),
  remove: (id: string) => api.delete<void>(`/assets/${id}/`),
  recordValuation: (
    id: string,
    payload: {
      value_minor: number;
      as_of?: string | null;
      source?: ValuationSource;
      notes?: string;
    },
  ) => api.post<TangibleAsset>(`/assets/${id}/valuations/`, payload),
};
