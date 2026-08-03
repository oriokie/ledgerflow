import { describe, expect, it } from "vitest";
import type { Category, FinancialAccount } from "../../api/types";
import {
  activeFilterChips,
  clearFilterField,
  countActiveFilters,
  EMPTY_FILTERS,
  filtersToParams,
  parseCursor,
  parseFilters,
  toApiFilters,
  type FilterState,
} from "./filters";

const accounts: FinancialAccount[] = [
  { id: "a1", name: "Checking", account_type: "checking", currency: "USD", balance_minor: 0 },
];
const categories: Category[] = [
  { id: "c1", name: "Groceries", kind: "expense", path: "Groceries", depth: 0, parent_id: null },
];

describe("parseFilters / filtersToParams", () => {
  it("round-trips through URL params, dropping empties", () => {
    const state: FilterState = {
      ...EMPTY_FILTERS,
      q: "coffee",
      account: "a1",
      type: "expense",
      start: "2024-01-01",
      needsReview: true,
    };
    const params = filtersToParams(state);
    expect(params.get("q")).toBe("coffee");
    expect(params.get("review")).toBe("1");
    expect(params.has("max")).toBe(false); // empty dropped

    expect(parseFilters(params)).toEqual(state);
  });
});

describe("toApiFilters", () => {
  it("maps UI field names, converts amounts to minor units, and bounds dates", () => {
    const api = toApiFilters({
      ...EMPTY_FILTERS,
      q: "rent",
      account: "a1",
      category: "c1",
      type: "expense",
      status: "posted",
      start: "2024-01-05",
      end: "2024-01-31",
      min: "10.50",
      max: "200",
      needsReview: true,
    });
    expect(api.search).toBe("rent");
    expect(api.account_id).toBe("a1");
    expect(api.category_id).toBe("c1");
    expect(api.type).toBe("expense");
    expect(api.status).toBe("posted");
    expect(api.start).toBe("2024-01-05T00:00:00.000Z");
    expect(api.end).toBe("2024-01-31T23:59:59.999Z");
    expect(api.min_amount_minor).toBe(1050);
    expect(api.max_amount_minor).toBe(20000);
    expect(api.needs_review).toBe(true);
  });

  it("passes a cursor when paginating and omits empty fields", () => {
    const api = toApiFilters(EMPTY_FILTERS, "CURSOR123");
    expect(api.cursor).toBe("CURSOR123");
    expect(api.search).toBeUndefined();
    expect(api.account_id).toBeUndefined();
  });
});

describe("countActiveFilters", () => {
  it("counts set filters but not free-text search", () => {
    expect(countActiveFilters({ ...EMPTY_FILTERS, q: "only search" })).toBe(0);
    expect(countActiveFilters({ ...EMPTY_FILTERS, account: "a1", type: "income", needsReview: true })).toBe(3);
  });
});

describe("activeFilterChips", () => {
  it("resolves names and lists each active filter", () => {
    const chips = activeFilterChips(
      { ...EMPTY_FILTERS, account: "a1", category: "c1", type: "expense" },
      { accounts, categories },
    );
    expect(chips.map((c) => c.label)).toEqual([
      "Account: Checking",
      "Type: expense",
      "Category: Groceries",
    ]);
  });
});

describe("clearFilterField", () => {
  it("clears a string field and the boolean review flag", () => {
    const base: FilterState = { ...EMPTY_FILTERS, account: "a1", needsReview: true };
    expect(clearFilterField(base, "account").account).toBe("");
    expect(clearFilterField(base, "needsReview").needsReview).toBe(false);
  });
});

describe("parseCursor", () => {
  it("extracts the cursor param from a page URL", () => {
    expect(parseCursor("https://api.test/v1/finance/transactions/?cursor=abc123&x=1")).toBe("abc123");
    expect(parseCursor("/finance/transactions/?cursor=z9")).toBe("z9");
    expect(parseCursor(null)).toBeNull();
    expect(parseCursor("https://api.test/no-cursor/")).toBeNull();
  });
});
