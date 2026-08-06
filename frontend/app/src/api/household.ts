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

export type ChangeRequestStatus = "pending" | "approved" | "declined";

export interface ChangeRequest {
  id: string;
  financial_account_id: string;
  summary: string;
  payload: Record<string, unknown>;
  status: ChangeRequestStatus;
  requested_by_id: string;
  resolved_by_id: string | null;
  resolved_at: string | null;
  created_at: string;
}

export const changeRequestApi = {
  /** Only the account's owner and the requester ever see these. */
  list: (status?: ChangeRequestStatus) =>
    api.get<{ results: ChangeRequest[] }>(
      `/household/change-requests/${status ? `?status=${status}` : ""}`,
    ),
  submit: (body: {
    financial_account_id: string;
    payload: Record<string, unknown>;
    summary?: string;
  }) => api.post<ChangeRequest>("/household/change-requests/", body),
  approve: (id: string) =>
    api.post<ChangeRequest & { applied: Record<string, { before: unknown; after: unknown }> }>(
      `/household/change-requests/${id}/approve/`,
      {},
    ),
  decline: (id: string) =>
    api.post<ChangeRequest>(`/household/change-requests/${id}/decline/`, {}),
};

/* ---------------------------------------------------------------- contributions */

export type ContributionMode = "equal" | "percentage" | "fixed" | "income_based";

export interface ContributionLine {
  membership_id: string;
  display_name: string;
  amount_minor: number;
  share_of_total: number;
  /** Why this figure is what it is — "why am I paying 62%" is the question
   *  the number always provokes, so the answer travels with it. */
  basis: string;
}

export interface ContributionPlan {
  mode: ContributionMode;
  currency: string;
  target_minor: number;
  /** False when the household has not agreed, or an input is missing. The UI
   *  must show `blockers` rather than inventing a split nobody chose. */
  is_complete: boolean;
  shortfall_minor: number;
  blockers: string[];
  notes: string[];
  contributions: ContributionLine[];
}

export interface FairnessLine {
  membership_id: string;
  display_name: string;
  expected_minor: number;
  actual_minor: number;
  /** Positive means they put in more than agreed. */
  delta_minor: number;
}

export interface Fairness {
  is_balanced: boolean;
  summary: string;
  worst_gap_minor: number;
  lines: FairnessLine[];
}

export interface ContributionOverview {
  agreement_id: string | null;
  review_on: string | null;
  plan: ContributionPlan;
  fairness: Fairness;
  derived_target_minor: number;
  /** Income landing in an account nobody owns. Reported, never distributed. */
  unattributed_income_minor: number;
}

export const contributionApi = {
  get: () => api.get<ContributionOverview>("/household/contributions/"),
  set: (body: {
    mode: ContributionMode;
    currency: string;
    target_minor?: number | null;
    review_on?: string | null;
    notes?: string;
    terms?: Record<string, { share?: string; fixed_minor?: number }>;
  }) => api.put<{ agreement_id: string }>("/household/contributions/", body),
};

/* -------------------------------------------------------------------- activity */

export interface ActivityEvent {
  id: string;
  occurred_at: string;
  actor: string;
  action: string;
  subject_type: string;
  subject_id: string | null;
  summary: string;
  /** Recorded and shown, with specifics omitted. Its existence is not the
   *  secret — a timeline with silent gaps is itself informative. */
  is_private: boolean;
  detail: Record<string, unknown>;
}

export const activityApi = {
  list: (params: { limit?: number; subject_type?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.limit) qs.set("limit", String(params.limit));
    if (params.subject_type) qs.set("subject_type", params.subject_type);
    const suffix = qs.toString() ? `?${qs}` : "";
    return api.get<ActivityEvent[]>(`/household/activity/${suffix}`);
  },
};

/* ------------------------------------------------------------------- approvals */

/** REQUESTED means the money has not moved and approving permits a purchase.
 *  FLAGGED means it already moved and approving is a review. The UI must never
 *  present one as the other. */
export type ApprovalKind = "requested" | "flagged";
export type ApprovalStatus =
  | "pending"
  | "approved"
  | "declined"
  | "expired"
  | "withdrawn";

export interface ApprovalComment {
  author: string;
  body: string;
  at: string;
}

export interface SpendApproval {
  id: string;
  kind: ApprovalKind;
  status: ApprovalStatus;
  amount_minor: number;
  suggested_amount_minor: number | null;
  currency: string;
  description: string;
  requested_by: string;
  resolved_by: string;
  expires_at: string | null;
  resolved_at: string | null;
  created_at: string;
  comments: ApprovalComment[];
}

export interface ApprovalRule {
  id: string;
  name: string;
  scope: string;
  currency: string;
  min_amount_minor: number;
  expires_after_hours: number;
  is_active: boolean;
}

export const approvalApi = {
  list: (status?: "pending") =>
    api.get<SpendApproval[]>(`/household/approvals/${status ? `?status=${status}` : ""}`),
  request: (body: {
    amount_minor: number;
    currency: string;
    description: string;
    financial_account_id?: string;
  }) => api.post<SpendApproval>("/household/approvals/", body),
  act: (
    id: string,
    body: { action: "approve" | "decline" | "suggest" | "withdraw" | "comment"; note?: string; amount_minor?: number },
  ) => api.post<SpendApproval>(`/household/approvals/${id}/`, body),
  rules: () => api.get<ApprovalRule[]>("/household/approval-rules/"),
  addRule: (body: { min_amount_minor: number; currency?: string; expires_after_hours?: number }) =>
    api.post<{ id: string }>("/household/approval-rules/", body),
};
