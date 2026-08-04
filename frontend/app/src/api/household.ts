import { api } from "./client";

export type SharingPolicy = "private" | "shared" | "read_only" | "approval_required";

export interface HouseholdMember {
  membership_id: string;
  display_name: string;
  relationship: string;
  contribution_share: number | null;
  visible_account_count: number;
  is_you: boolean;
}

export interface CombinedPosition {
  currency: string;
  as_of: string;
  total_assets_minor: number;
  total_liabilities_minor: number;
  net_worth_minor: number;
  visible_assets_minor: number;
  visible_liabilities_minor: number;
  /** How much of the total this viewer cannot itemise. Disclosed, not hidden. */
  withheld_account_count: number;
  members: HouseholdMember[];
  dependants: number;
  notes: string[];
}

export interface ExpenseSplit {
  currency: string;
  monthly_dependant_cost_minor: number;
  per_member: {
    membership_id: string;
    display_name: string;
    share: number | null;
    monthly_minor: number | null;
  }[];
  notes: string[];
}

export interface Coverage {
  currency: string;
  monthly_expenses_minor: number;
  household_liquid_minor: number;
  household_runway_months: number;
  visible_runway_months: number;
  notes: string[];
}

export interface HouseholdSummary {
  position: CombinedPosition;
  expense_split: ExpenseSplit;
  coverage: Coverage;
}

export interface Dependant {
  id: string;
  name: string;
  relationship: string;
  birth_year: number | null;
  monthly_cost_minor: number | null;
  support_until_year: number | null;
  notes: string;
}

export interface AccountSharingRow {
  financial_account_id: string;
  policy: SharingPolicy;
  is_joint: boolean;
  owner_membership_id: string | null;
  visible_to_household: boolean;
  writable_by_household: boolean;
}

export const householdApi = {
  summary: () => api.get<HouseholdSummary>("/household/summary/"),
  members: () => api.get<{ results: HouseholdMember[] }>("/household/members/"),
  updateMyProfile: (body: {
    display_name?: string;
    relationship?: string;
    contribution_share?: string | null;
  }) => api.patch<HouseholdMember>("/household/members/", body),

  dependants: () => api.get<{ results: Dependant[] }>("/household/dependants/"),
  addDependant: (body: Partial<Dependant>) =>
    api.post<Dependant>("/household/dependants/", body),
  removeDependant: (id: string) => api.delete<void>(`/household/dependants/${id}/`),

  sharing: () => api.get<{ results: AccountSharingRow[] }>("/household/sharing/"),
  setSharing: (
    accountId: string,
    body: { policy: SharingPolicy; is_joint?: boolean },
  ) => api.put<AccountSharingRow>(`/household/sharing/${accountId}/`, body),
  backfill: () =>
    api.post<{ created: number; detail: string }>("/household/sharing/backfill/", {}),
};
