/**
 * Token + active-tenant storage.
 *
 * Deliberately NOT localStorage for the refresh token in a "real" production
 * app (XSS exposure) — but LedgerFlow's API is bearer-token-only with no
 * first-party cookie support today, so there is no lower-risk transport
 * available without a backend change (an httpOnly-cookie refresh endpoint).
 * Kept centralized here so that swap is a one-file change later.
 */

const ACCESS_KEY = "lf_access_token";
const REFRESH_KEY = "lf_refresh_token";
const TENANT_KEY = "lf_active_tenant_id";

export const tokenStore = {
  getAccess: () => localStorage.getItem(ACCESS_KEY),
  getRefresh: () => localStorage.getItem(REFRESH_KEY),
  setTokens: (access: string, refresh: string) => {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  setAccess: (access: string) => localStorage.setItem(ACCESS_KEY, access),
  clear: () => {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

export const tenantStore = {
  getActive: () => localStorage.getItem(TENANT_KEY),
  setActive: (tenantId: string) => localStorage.setItem(TENANT_KEY, tenantId),
  clear: () => localStorage.removeItem(TENANT_KEY),
};
