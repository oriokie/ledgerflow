import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { attachmentsApi, financeApi } from "../api/finance";
import { useAuth } from "../lib/AuthContext";
import { useBulkUpdateTransactions, useBulkVoidTransactions, useUploadReceipt } from "./useFinance";

vi.mock("../api/finance", () => ({
  financeApi: { bulkTransactions: vi.fn() },
  financeExtendedApi: {},
  walletsApi: {},
  attachmentsApi: { requestUpload: vi.fn(), directUpload: vi.fn(), confirm: vi.fn() },
}));
vi.mock("../lib/AuthContext", () => ({ useAuth: vi.fn() }));

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}
function freshClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useAuth).mockReturnValue({ activeWorkspace: { tenant: { id: "t1" } } } as never);
});

describe("bulk transaction hooks call the batch endpoint", () => {
  it("categorize sends one request and maps requested/failed", async () => {
    vi.mocked(financeApi.bulkTransactions).mockResolvedValue({
      requested: 3,
      updated: 2,
      failed: [{ id: "x", error: "kind mismatch" }],
    } as never);

    const { result } = renderHook(() => useBulkUpdateTransactions(), { wrapper: wrapper(freshClient()) });
    const res = await result.current.mutateAsync({ ids: ["a", "b", "c"], payload: { category_id: "cat" } });

    expect(financeApi.bulkTransactions).toHaveBeenCalledWith({
      action: "categorize",
      ids: ["a", "b", "c"],
      category_id: "cat",
    });
    expect(res).toEqual({ total: 3, failed: 1 });
  });

  it("void sends the void action in one request", async () => {
    vi.mocked(financeApi.bulkTransactions).mockResolvedValue({ requested: 2, updated: 2, failed: [] } as never);

    const { result } = renderHook(() => useBulkVoidTransactions(), { wrapper: wrapper(freshClient()) });
    const res = await result.current.mutateAsync({ ids: ["a", "b"] });

    expect(financeApi.bulkTransactions).toHaveBeenCalledWith({ action: "void", ids: ["a", "b"] });
    expect(res).toEqual({ total: 2, failed: 0 });
  });
});

describe("useUploadReceipt", () => {
  it("falls back to a direct upload when the backend can't presign", async () => {
    vi.mocked(attachmentsApi.requestUpload).mockResolvedValue({ id: "att1", upload_url: null } as never);
    vi.mocked(attachmentsApi.directUpload).mockResolvedValue({ id: "att1", status: "uploaded" } as never);

    const file = new File([new Uint8Array([1, 2, 3])], "r.pdf", { type: "application/pdf" });
    const { result } = renderHook(() => useUploadReceipt("txn1"), { wrapper: wrapper(freshClient()) });
    await result.current.mutateAsync(file);

    expect(attachmentsApi.requestUpload).toHaveBeenCalledWith("txn1", {
      filename: "r.pdf",
      content_type: "application/pdf",
      byte_size: 3,
    });
    expect(attachmentsApi.directUpload).toHaveBeenCalledWith("att1", file);
    expect(attachmentsApi.confirm).not.toHaveBeenCalled();
  });

  it("uses the presigned PUT then confirms when storage can presign", async () => {
    vi.mocked(attachmentsApi.requestUpload).mockResolvedValue({ id: "att2", upload_url: "https://s3/put" } as never);
    vi.mocked(attachmentsApi.confirm).mockResolvedValue({ id: "att2", status: "uploaded" } as never);
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    const file = new File([new Uint8Array([9])], "r.png", { type: "image/png" });
    const { result } = renderHook(() => useUploadReceipt("txn2"), { wrapper: wrapper(freshClient()) });
    await result.current.mutateAsync(file);

    expect(fetchMock).toHaveBeenCalledWith("https://s3/put", expect.objectContaining({ method: "PUT" }));
    expect(attachmentsApi.directUpload).not.toHaveBeenCalled();
    expect(attachmentsApi.confirm).toHaveBeenCalledWith("att2", "");

    vi.unstubAllGlobals();
  });
});
