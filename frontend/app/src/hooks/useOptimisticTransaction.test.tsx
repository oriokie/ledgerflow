import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Paginated, Transaction } from "../api/types";

const updateTransaction = vi.fn();

vi.mock("../api/finance", () => ({
  financeApi: {},
  financeExtendedApi: { updateTransaction: (...args: unknown[]) => updateTransaction(...args) },
}));
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { tenant: { id: "t1" } } }),
}));

import { useUpdateTransaction } from "./useFinance";

const TXN_KEY = ["transactions", "t1", { page_size: 25 }];

function seed(client: QueryClient) {
  const page: Paginated<Transaction> = {
    next: null,
    previous: null,
    results: [
      { id: "a", category_id: null, memo: "Whole Foods" } as Transaction,
      { id: "b", category_id: "cat-old", memo: "Payroll" } as Transaction,
    ],
  };
  client.setQueryData(TXN_KEY, page);
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function rows(client: QueryClient) {
  return client.getQueryData<Paginated<Transaction>>(TXN_KEY)!.results;
}

beforeEach(() => vi.clearAllMocks());

describe("useUpdateTransaction — optimistic categorization", () => {
  it("applies the new category to the cache before the server replies", async () => {
    const client = makeClient();
    seed(client);
    // A request that never settles: whatever the UI shows now is purely optimistic.
    updateTransaction.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useUpdateTransaction(), { wrapper: wrapper(client) });

    act(() => {
      result.current.mutate({ txnId: "a", payload: { category_id: "cat-groceries" } });
    });

    await waitFor(() => expect(rows(client)[0].category_id).toBe("cat-groceries"));
    // Other rows are untouched.
    expect(rows(client)[1].category_id).toBe("cat-old");
  });

  it("rolls the cache back when the save fails", async () => {
    const client = makeClient();
    seed(client);
    updateTransaction.mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useUpdateTransaction(), { wrapper: wrapper(client) });

    act(() => {
      result.current.mutate({ txnId: "a", payload: { category_id: "cat-groceries" } });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    // A failed edit must never leave a wrong category on screen looking saved.
    expect(rows(client)[0].category_id).toBeNull();
  });

  it("keeps the optimistic value after a successful save", async () => {
    const client = makeClient();
    seed(client);
    updateTransaction.mockResolvedValue({ id: "a", category_id: "cat-groceries" });

    const { result } = renderHook(() => useUpdateTransaction(), { wrapper: wrapper(client) });

    act(() => {
      result.current.mutate({ txnId: "a", payload: { category_id: "cat-groceries" } });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(rows(client)[0].category_id).toBe("cat-groceries");
  });

  it("patches a memo edit without disturbing the rest of the row", async () => {
    const client = makeClient();
    seed(client);
    updateTransaction.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useUpdateTransaction(), { wrapper: wrapper(client) });

    act(() => {
      result.current.mutate({ txnId: "b", payload: { memo: "Salary — March" } });
    });

    await waitFor(() => expect(rows(client)[1].memo).toBe("Salary — March"));
    expect(rows(client)[1].category_id).toBe("cat-old");
  });
});
