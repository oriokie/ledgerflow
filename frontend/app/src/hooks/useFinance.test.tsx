import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { financeApi } from "../api/finance";
import { useAuth } from "../lib/AuthContext";
import { useCategories, useCreateCategory } from "./useFinance";

vi.mock("../api/finance", () => ({
  financeApi: { listCategories: vi.fn(), createCategory: vi.fn() },
  financeExtendedApi: { updateCategory: vi.fn(), deleteCategory: vi.fn() },
}));

vi.mock("../lib/AuthContext", () => ({ useAuth: vi.fn() }));

const WORKSPACE = { activeWorkspace: { tenant: { id: "t1" } } };
const NO_WORKSPACE = { activeWorkspace: null };

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

function freshClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

beforeEach(() => {
  vi.mocked(financeApi.listCategories).mockReset();
  vi.mocked(financeApi.createCategory).mockReset();
});

describe("useCategories — tenant-gated query", () => {
  it("does NOT fetch until a workspace is active (cross-tenant guard)", async () => {
    vi.mocked(useAuth).mockReturnValue(NO_WORKSPACE as never);
    const { result } = renderHook(() => useCategories(), { wrapper: wrapper(freshClient()) });

    // enabled:false → query never runs
    expect(result.current.fetchStatus).toBe("idle");
    expect(financeApi.listCategories).not.toHaveBeenCalled();
  });

  it("fetches and returns categories once a workspace is active", async () => {
    vi.mocked(useAuth).mockReturnValue(WORKSPACE as never);
    vi.mocked(financeApi.listCategories).mockResolvedValue([
      { id: "c1", name: "Groceries", kind: "expense", path: "Groceries", currency: "USD" },
    ] as never);

    const { result } = renderHook(() => useCategories(), { wrapper: wrapper(freshClient()) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data?.[0].name).toBe("Groceries");
    expect(financeApi.listCategories).toHaveBeenCalledOnce();
  });
});

describe("useCreateCategory — mutation invalidates the cache", () => {
  it("calls the API and invalidates the categories query on success", async () => {
    vi.mocked(useAuth).mockReturnValue(WORKSPACE as never);
    vi.mocked(financeApi.createCategory).mockResolvedValue({ id: "c9" } as never);

    const client = freshClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateCategory(), { wrapper: wrapper(client) });
    await result.current.mutateAsync({ name: "Rent", kind: "expense", currency: "USD" } as never);

    // React Query v5 calls mutationFn as (variables, context) — assert the payload arg.
    expect(vi.mocked(financeApi.createCategory).mock.calls[0][0]).toEqual({
      name: "Rent",
      kind: "expense",
      currency: "USD",
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["categories"] });
  });
});
