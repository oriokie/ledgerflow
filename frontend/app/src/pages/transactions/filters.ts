import type { TransactionFilters } from "../../api/finance";
import type { Category, FinancialAccount } from "../../api/types";
import { majorToMinor } from "../../lib/money";

export type TxnType = "" | "expense" | "income" | "transfer";

export interface FilterState {
  q: string;
  account: string;
  category: string;
  type: TxnType;
  status: string;
  start: string; // YYYY-MM-DD
  end: string; // YYYY-MM-DD
  min: string; // major units
  max: string; // major units
  needsReview: boolean;
}

export const EMPTY_FILTERS: FilterState = {
  q: "",
  account: "",
  category: "",
  type: "",
  status: "",
  start: "",
  end: "",
  min: "",
  max: "",
  needsReview: false,
};

/** Read filter state from URL search params (shareable, reload-safe). */
export function parseFilters(params: URLSearchParams): FilterState {
  return {
    q: params.get("q") ?? "",
    account: params.get("account") ?? "",
    category: params.get("category") ?? "",
    type: (params.get("type") as TxnType) ?? "",
    status: params.get("status") ?? "",
    start: params.get("start") ?? "",
    end: params.get("end") ?? "",
    min: params.get("min") ?? "",
    max: params.get("max") ?? "",
    needsReview: params.get("review") === "1",
  };
}

/** Serialize non-empty filters to URL params (drops empty keys for clean URLs). */
export function filtersToParams(state: FilterState): URLSearchParams {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  if (state.account) p.set("account", state.account);
  if (state.category) p.set("category", state.category);
  if (state.type) p.set("type", state.type);
  if (state.status) p.set("status", state.status);
  if (state.start) p.set("start", state.start);
  if (state.end) p.set("end", state.end);
  if (state.min) p.set("min", state.min);
  if (state.max) p.set("max", state.max);
  if (state.needsReview) p.set("review", "1");
  return p;
}

/** Map UI filter state to the API's TransactionFilters (names + units + dates). */
export function toApiFilters(state: FilterState, cursor?: string): TransactionFilters {
  const api: TransactionFilters = {};
  if (state.q) api.search = state.q;
  if (state.account) api.account_id = state.account;
  if (state.category) api.category_id = state.category;
  if (state.type) api.type = state.type;
  if (state.status) api.status = state.status;
  if (state.start) api.start = `${state.start}T00:00:00.000Z`;
  if (state.end) api.end = `${state.end}T23:59:59.999Z`;
  if (state.min && !Number.isNaN(Number(state.min))) api.min_amount_minor = majorToMinor(Number(state.min));
  if (state.max && !Number.isNaN(Number(state.max))) api.max_amount_minor = majorToMinor(Number(state.max));
  if (state.needsReview) api.needs_review = true;
  if (cursor) api.cursor = cursor;
  return api;
}

/** How many filters (beyond free-text search) are active — drives a badge. */
export function countActiveFilters(state: FilterState): number {
  let n = 0;
  if (state.account) n++;
  if (state.category) n++;
  if (state.type) n++;
  if (state.status) n++;
  if (state.start) n++;
  if (state.end) n++;
  if (state.min) n++;
  if (state.max) n++;
  if (state.needsReview) n++;
  return n;
}

export interface FilterChip {
  /** The FilterState field this chip clears. */
  key: keyof FilterState;
  label: string;
}

/**
 * The active filters as human-readable, removable chips. Names are resolved
 * from the provided account/category lookups where possible.
 */
export function activeFilterChips(
  state: FilterState,
  lookups: { accounts?: FinancialAccount[]; categories?: Category[] },
): FilterChip[] {
  const chips: FilterChip[] = [];
  const accountName = lookups.accounts?.find((a) => a.id === state.account)?.name;
  const categoryName = lookups.categories?.find((c) => c.id === state.category)?.name;

  if (state.account) chips.push({ key: "account", label: `Account: ${accountName ?? "—"}` });
  if (state.type) chips.push({ key: "type", label: `Type: ${state.type}` });
  if (state.category) chips.push({ key: "category", label: `Category: ${categoryName ?? "—"}` });
  if (state.status) chips.push({ key: "status", label: `Status: ${state.status}` });
  if (state.start) chips.push({ key: "start", label: `From ${state.start}` });
  if (state.end) chips.push({ key: "end", label: `To ${state.end}` });
  if (state.min) chips.push({ key: "min", label: `≥ ${state.min}` });
  if (state.max) chips.push({ key: "max", label: `≤ ${state.max}` });
  if (state.needsReview) chips.push({ key: "needsReview", label: "Needs review" });
  return chips;
}

/** Clear a single filter field, returning a new state. */
export function clearFilterField(state: FilterState, key: keyof FilterState): FilterState {
  return { ...state, [key]: key === "needsReview" ? false : "" };
}

/** Extract the opaque `cursor` value from a paginated `next`/`previous` URL. */
export function parseCursor(url: string | null): string | null {
  if (!url) return null;
  try {
    const u = new URL(url, "http://x");
    return u.searchParams.get("cursor");
  } catch {
    return null;
  }
}
