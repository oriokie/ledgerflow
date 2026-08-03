import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthTokens, MfaRequired } from "../api/types";
import { AuthProvider, useAuth } from "./AuthContext";
import { tenantStore, tokenStore } from "../api/tokenStore";
import { tenancyApi } from "../api/tenancy";

vi.mock("../api/auth", () => ({
  authApi: { login: vi.fn(), verifyMfa: vi.fn(), me: vi.fn(), logout: vi.fn() },
  // real pure logic — the funnel branches on this
  isMfaRequired: (r: AuthTokens | MfaRequired) => "mfa_required" in r && r.mfa_required === true,
}));

vi.mock("../api/tenancy", () => ({
  tenancyApi: { listWorkspaces: vi.fn() },
}));

vi.mock("../api/tokenStore", () => ({
  tokenStore: { getAccess: vi.fn(() => null), getRefresh: vi.fn(), setTokens: vi.fn(), clear: vi.fn() },
  tenantStore: { getActive: vi.fn(() => null), setActive: vi.fn(), clear: vi.fn() },
}));

const OK_RESPONSE: AuthTokens = {
  access: "acc",
  refresh: "ref",
  user: { id: "u1", email: "demo@ledgerflow.test" },
};
const MFA_RESPONSE: MfaRequired = { mfa_required: true, mfa_token: "chal-123", methods: ["totp"] };

function Probe({ res }: { res: AuthTokens | MfaRequired }) {
  const { completeLogin, isAuthenticated } = useAuth();
  const [result, setResult] = useState("");
  return (
    <>
      <button onClick={async () => setResult(JSON.stringify(await completeLogin(res)))}>go</button>
      <span data-testid="authed">{String(isAuthenticated)}</span>
      <span data-testid="result">{result}</span>
    </>
  );
}

describe("AuthContext.completeLogin — the shared session funnel", () => {
  beforeEach(() => {
    vi.mocked(tokenStore.setTokens).mockReset();
    vi.mocked(tenantStore.setActive).mockReset();
    vi.mocked(tenancyApi.listWorkspaces).mockReset();
  });

  it("establishes a session for a token response", async () => {
    const user = userEvent.setup();
    vi.mocked(tenancyApi.listWorkspaces).mockResolvedValue([
      { tenant: { id: "t1", name: "Demo", base_currency: "USD" }, role: "owner" },
    ] as never);

    render(
      <AuthProvider>
        <Probe res={OK_RESPONSE} />
      </AuthProvider>,
    );
    await user.click(screen.getByRole("button", { name: "go" }));

    await waitFor(() => expect(screen.getByTestId("result")).toHaveTextContent('"status":"ok"'));
    expect(tokenStore.setTokens).toHaveBeenCalledWith("acc", "ref");
    // active tenant chosen from the loaded workspaces
    expect(tenantStore.setActive).toHaveBeenCalledWith("t1");
    expect(screen.getByTestId("authed")).toHaveTextContent("true");
  });

  it("returns an mfa challenge WITHOUT starting a session", async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <Probe res={MFA_RESPONSE} />
      </AuthProvider>,
    );
    await user.click(screen.getByRole("button", { name: "go" }));

    await waitFor(() =>
      expect(screen.getByTestId("result")).toHaveTextContent('"status":"mfa_required"'),
    );
    expect(screen.getByTestId("result")).toHaveTextContent("chal-123");
    // crucially: no tokens persisted, not authenticated, no workspace fetch
    expect(tokenStore.setTokens).not.toHaveBeenCalled();
    expect(tenancyApi.listWorkspaces).not.toHaveBeenCalled();
    expect(screen.getByTestId("authed")).toHaveTextContent("false");
  });
});
