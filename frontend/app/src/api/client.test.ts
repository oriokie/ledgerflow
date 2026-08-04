import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./client";
import { tenantStore, tokenStore } from "./tokenStore";

vi.mock("./tokenStore", () => ({
  tokenStore: {
    getAccess: vi.fn(),
    getRefresh: vi.fn(),
    setAccess: vi.fn(),
    setTokens: vi.fn(),
    clear: vi.fn(),
  },
  tenantStore: { getActive: vi.fn(), setActive: vi.fn(), clear: vi.fn() },
}));

/** Minimal Response stand-in — the client only touches ok/status/headers.get/json/text. */
function makeResponse(status: number, body: unknown, contentType = "application/json"): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (h: string) => (h.toLowerCase() === "content-type" ? contentType : null) },
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  } as unknown as Response;
}

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  vi.mocked(tokenStore.getAccess).mockReturnValue(null);
  vi.mocked(tokenStore.getRefresh).mockReturnValue(null);
  vi.mocked(tenantStore.getActive).mockReturnValue(null);
  vi.mocked(tokenStore.setAccess).mockClear();
  vi.mocked(tokenStore.clear).mockClear();
  vi.mocked(tenantStore.clear).mockClear();
});

afterEach(() => vi.unstubAllGlobals());

/** Pull the headers object the client passed to a given fetch call. */
function headersOfCall(callIndex = 0): Record<string, string> {
  return (fetchMock.mock.calls[callIndex][1] as RequestInit).headers as Record<string, string>;
}

describe("ApiError.parse — normalizes every error shape into detail + fieldErrors", () => {
  it("prefers a specific field message from the { error: { details } } envelope", () => {
    const e = new ApiError(400, {
      error: { code: "validation_error", message: "Invalid input", details: { email: ["Already taken."] } },
    });
    expect(e.detail).toBe("Already taken.");
    expect(e.code).toBe("validation_error");
    expect(e.fieldErrors).toEqual({ email: ["Already taken."] });
  });

  it("falls back to the envelope message when there are no field details", () => {
    const e = new ApiError(403, { error: { code: "forbidden", message: "Not allowed." } });
    expect(e.detail).toBe("Not allowed.");
    expect(e.code).toBe("forbidden");
    expect(e.fieldErrors).toEqual({});
  });

  it("handles the bare { detail } shape", () => {
    const e = new ApiError(404, { detail: "Not found." });
    expect(e.detail).toBe("Not found.");
    expect(e.code).toBeNull();
  });

  it("handles bare field-error dicts", () => {
    const e = new ApiError(400, { password: ["Too short."], email: ["Bad."] });
    expect(e.fieldErrors).toEqual({ password: ["Too short."], email: ["Bad."] });
    expect(e.detail).toBe("Too short."); // first field's first message
  });

  it("degrades to a generic message for a non-object body", () => {
    expect(new ApiError(500, "boom").detail).toBe("Request failed.");
    expect(new ApiError(500, null).detail).toBe("Request failed.");
  });
});

describe("request — header injection", () => {
  it("adds Authorization when an access token is present", async () => {
    vi.mocked(tokenStore.getAccess).mockReturnValue("acc-1");
    fetchMock.mockResolvedValue(makeResponse(200, { ok: true }));
    await api.get("/thing/");
    expect(headersOfCall().Authorization).toBe("Bearer acc-1");
  });

  it("adds X-Tenant-ID when a workspace is active", async () => {
    vi.mocked(tenantStore.getActive).mockReturnValue("tenant-9");
    fetchMock.mockResolvedValue(makeResponse(200, {}));
    await api.get("/thing/");
    expect(headersOfCall()["X-Tenant-ID"]).toBe("tenant-9");
  });

  it("omits Authorization when skipAuth is set", async () => {
    vi.mocked(tokenStore.getAccess).mockReturnValue("acc-1");
    fetchMock.mockResolvedValue(makeResponse(200, {}));
    await api.post("/auth/login/", { email: "x" }, { skipAuth: true, skipTenant: true });
    expect(headersOfCall().Authorization).toBeUndefined();
    expect(headersOfCall()["X-Tenant-ID"]).toBeUndefined();
  });

  it("serializes the body and sets the method", async () => {
    fetchMock.mockResolvedValue(makeResponse(201, { id: "1" }));
    await api.post("/things/", { name: "New" }, { skipAuth: true, skipTenant: true });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ name: "New" }));
  });
});

describe("request — response handling", () => {
  it("returns parsed JSON on success", async () => {
    fetchMock.mockResolvedValue(makeResponse(200, { value: 42 }));
    await expect(api.get("/thing/")).resolves.toEqual({ value: 42 });
  });

  it("returns null — never undefined — for 204 No Content", async () => {
    fetchMock.mockResolvedValue(makeResponse(204, ""));
    await expect(api.delete("/thing/1/")).resolves.toBeNull();
  });

  // Regression: 204 used to resolve to `undefined`, which TanStack Query
  // rejects outright ("Query data cannot be undefined"). That turned every
  // legitimately-empty endpoint — an unfunded portfolio, a debt-free
  // workspace — into a page-level error instead of an empty state. The
  // distinction between null and undefined is load-bearing here, so assert
  // it explicitly rather than relying on a loose falsy check.
  it("resolves 204 to a value a query function may return", async () => {
    fetchMock.mockResolvedValue(makeResponse(204, ""));
    const data = await api.get<{ total: number } | null>("/investments/portfolio/");
    expect(data).toBeNull();
    expect(data).not.toBeUndefined();
  });

  it("throws an ApiError carrying status and parsed detail on failure", async () => {
    fetchMock.mockResolvedValue(makeResponse(400, { detail: "Nope." }));
    await expect(api.get("/thing/")).rejects.toMatchObject({
      name: "ApiError",
      status: 400,
      detail: "Nope.",
    });
  });
});

describe("request — 401 silent refresh", () => {
  it("refreshes once and retries the original request on 401", async () => {
    vi.mocked(tokenStore.getAccess).mockReturnValue("stale");
    vi.mocked(tokenStore.getRefresh).mockReturnValue("refresh-tok");

    fetchMock
      .mockResolvedValueOnce(makeResponse(401, { detail: "expired" })) // original
      .mockResolvedValueOnce(makeResponse(200, { access: "fresh" })) // refresh
      .mockResolvedValueOnce(makeResponse(200, { data: "ok" })); // retry

    await expect(api.get("/protected/")).resolves.toEqual({ data: "ok" });
    expect(tokenStore.setAccess).toHaveBeenCalledWith("fresh");
    // original + refresh + retry
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("stores the rotated refresh token, not just the access token", async () => {
    // The backend rotates and blacklists on every refresh. Discarding the
    // rotated token is why every session used to die ~30 minutes in: the
    // first refresh burned the stored token, the second presented the
    // blacklisted one, and the user was logged out mid-task.
    vi.mocked(tokenStore.getAccess).mockReturnValue("stale");
    vi.mocked(tokenStore.getRefresh).mockReturnValue("refresh-1");

    fetchMock
      .mockResolvedValueOnce(makeResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(makeResponse(200, { access: "fresh", refresh: "refresh-2" }))
      .mockResolvedValueOnce(makeResponse(200, { data: "ok" }));

    await expect(api.get("/protected/")).resolves.toEqual({ data: "ok" });
    expect(tokenStore.setTokens).toHaveBeenCalledWith("fresh", "refresh-2");
  });

  it("clears the session and signals expiry when refresh is impossible", async () => {
    vi.mocked(tokenStore.getAccess).mockReturnValue("stale");
    vi.mocked(tokenStore.getRefresh).mockReturnValue(null); // no refresh token
    fetchMock.mockResolvedValueOnce(makeResponse(401, { detail: "expired" }));

    const onExpired = vi.fn();
    window.addEventListener("lf:session-expired", onExpired);

    await expect(api.get("/protected/")).rejects.toMatchObject({ status: 401 });
    expect(tokenStore.clear).toHaveBeenCalled();
    expect(tenantStore.clear).toHaveBeenCalled();
    expect(onExpired).toHaveBeenCalledOnce();

    window.removeEventListener("lf:session-expired", onExpired);
  });

  it("does not attempt refresh for skipAuth requests", async () => {
    fetchMock.mockResolvedValueOnce(makeResponse(401, { detail: "bad creds" }));
    await expect(
      api.post("/auth/login/", { email: "x" }, { skipAuth: true, skipTenant: true }),
    ).rejects.toMatchObject({ status: 401 });
    // exactly one call — no refresh round-trip
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(tokenStore.clear).not.toHaveBeenCalled();
  });

  it("gives up if the retried request also 401s (no infinite loop)", async () => {
    vi.mocked(tokenStore.getAccess).mockReturnValue("stale");
    vi.mocked(tokenStore.getRefresh).mockReturnValue("refresh-tok");
    fetchMock
      .mockResolvedValueOnce(makeResponse(401, { detail: "expired" })) // original
      .mockResolvedValueOnce(makeResponse(200, { access: "fresh" })) // refresh
      .mockResolvedValueOnce(makeResponse(401, { detail: "still bad" })); // retry 401

    await expect(api.get("/protected/")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(3); // no fourth attempt
  });

  it("coalesces concurrent 401s into a single refresh call", async () => {
    vi.mocked(tokenStore.getAccess).mockReturnValue("stale");
    vi.mocked(tokenStore.getRefresh).mockReturnValue("refresh-tok");

    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/auth/refresh/")) return Promise.resolve(makeResponse(200, { access: "fresh" }));
      // both original calls 401 first, then succeed on retry
      const call = fetchMock.mock.calls.filter((c) => !String(c[0]).includes("/auth/refresh/")).length;
      return Promise.resolve(call <= 2 ? makeResponse(401, {}) : makeResponse(200, { ok: true }));
    });

    await Promise.all([api.get("/a/"), api.get("/b/")]);

    const refreshCalls = fetchMock.mock.calls.filter((c) => String(c[0]).includes("/auth/refresh/"));
    expect(refreshCalls).toHaveLength(1);
  });
});
