import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { authApi, isMfaRequired } from "../api/auth";
import { ApiError } from "../api/client";
import { tenancyApi } from "../api/tenancy";
import { tenantStore, tokenStore } from "../api/tokenStore";
import type { AuthTokens, MfaRequired, User, Workspace } from "../api/types";

interface AuthContextValue {
  user: User | null;
  workspaces: Workspace[];
  activeWorkspace: Workspace | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  /** Resolves to "ok", or "mfa_required" with a challenge token to hand to verifyMfa. */
  login: (email: string, password: string) => Promise<LoginResult>;
  /** Establish a session from an already-obtained login response (OAuth, passkey). */
  completeLogin: (res: AuthTokens | MfaRequired) => Promise<LoginResult>;
  verifyMfa: (mfaToken: string, code: string) => Promise<void>;
  logout: () => Promise<void>;
  switchWorkspace: (tenantId: string) => void;
  refreshWorkspaces: () => Promise<void>;
  /** Re-read the signed-in user. For preferences that live on the account
   *  rather than the device, so a change is reflected everywhere the user
   *  object is read — the sidebar included — without a page reload. */
  refreshUser: () => Promise<void>;
}

type LoginResult = { status: "ok" } | { status: "mfa_required"; mfaToken: string };

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeTenantId, setActiveTenantId] = useState<string | null>(tenantStore.getActive());
  const [isLoading, setIsLoading] = useState(true);

  const bootstrap = useCallback(async () => {
    if (!tokenStore.getAccess()) {
      setIsLoading(false);
      return;
    }
    try {
      const [me, ws] = await Promise.all([authApi.me(), tenancyApi.listWorkspaces()]);
      setUser(me);
      setWorkspaces(ws);
      // If there's no active tenant yet (fresh login) or the stored one no
      // longer exists in the membership list, default to the first workspace.
      const stillValid = ws.some((w) => w.tenant.id === activeTenantId);
      if (!stillValid && ws.length > 0) {
        tenantStore.setActive(ws[0].tenant.id);
        setActiveTenantId(ws[0].tenant.id);
      }
    } catch (err) {
      // Only a definitive rejection ends the session. Clearing tokens on any
      // failure turned every network blip during startup into a logout — the
      // session died because the wifi did.
      if (err instanceof ApiError && err.status === 401) {
        tokenStore.clear();
        tenantStore.clear();
      }
      setUser(null);
    } finally {
      setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bootstrap();
    const onExpired = () => {
      setUser(null);
      setWorkspaces([]);
    };
    window.addEventListener("lf:session-expired", onExpired);
    return () => window.removeEventListener("lf:session-expired", onExpired);
  }, [bootstrap]);

  // Every successful auth path (password, MFA, OAuth, passkey) ends here: persist
  // tokens, set the user, load workspaces, and pick an active one. Keeping this in
  // one place means new sign-in methods can't drift from the established session shape.
  const applySession = useCallback(async (res: AuthTokens) => {
    tokenStore.setTokens(res.access, res.refresh);
    setUser(res.user);
    const ws = await tenancyApi.listWorkspaces();
    setWorkspaces(ws);
    if (ws.length > 0) {
      tenantStore.setActive(ws[0].tenant.id);
      setActiveTenantId(ws[0].tenant.id);
    }
  }, []);

  // Turn any login response into a uniform result: either the session is
  // established, or the caller must collect a second factor.
  const completeLogin = useCallback(
    async (res: AuthTokens | MfaRequired): Promise<LoginResult> => {
      if (isMfaRequired(res)) {
        return { status: "mfa_required", mfaToken: res.mfa_token };
      }
      await applySession(res);
      return { status: "ok" };
    },
    [applySession],
  );

  const login = useCallback(
    async (email: string, password: string) => completeLogin(await authApi.login(email, password)),
    [completeLogin],
  );

  const verifyMfa = useCallback(
    async (mfaToken: string, code: string) => {
      await applySession(await authApi.verifyMfa(mfaToken, code));
    },
    [applySession],
  );

  const logout = useCallback(async () => {
    const refresh = tokenStore.getRefresh();
    try {
      if (refresh) await authApi.logout(refresh);
    } catch {
      // best-effort — clear local state regardless of whether the blacklist call succeeds
    }
    tokenStore.clear();
    tenantStore.clear();
    setUser(null);
    setWorkspaces([]);
    setActiveTenantId(null);
  }, []);

  const switchWorkspace = useCallback((tenantId: string) => {
    tenantStore.setActive(tenantId);
    setActiveTenantId(tenantId);
    // A full reload is the simplest way to guarantee every query re-fetches
    // under the new tenant context — cross-tenant data must never bleed
    // between workspace switches, and this makes that structurally impossible.
    window.location.href = "/";
  }, []);

  const refreshUser = useCallback(async () => {
    setUser(await authApi.me());
  }, []);

  const refreshWorkspaces = useCallback(async () => {
    const ws = await tenancyApi.listWorkspaces();
    setWorkspaces(ws);
  }, []);

  const activeWorkspace = useMemo(
    () => workspaces.find((w) => w.tenant.id === activeTenantId) ?? null,
    [workspaces, activeTenantId],
  );

  const value: AuthContextValue = {
    user,
    workspaces,
    activeWorkspace,
    isAuthenticated: !!user,
    isLoading,
    login,
    completeLogin,
    verifyMfa,
    logout,
    switchWorkspace,
    refreshWorkspaces,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
