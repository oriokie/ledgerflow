import { api } from "./client";
import type { AuthTokens, MfaRequired, TotpEnrollment, User, WebAuthnCredential } from "./types";

export const authApi = {
  login: (email: string, password: string) =>
    api.post<AuthTokens | MfaRequired>("/auth/login/", { email, password }, { skipAuth: true, skipTenant: true }),

  verifyMfa: (mfa_token: string, code: string) =>
    api.post<AuthTokens>("/auth/mfa/verify/", { mfa_token, code }, { skipAuth: true, skipTenant: true }),

  register: (payload: { email: string; password: string; first_name?: string; last_name?: string }) =>
    api.post<User>("/auth/register/", payload, { skipAuth: true, skipTenant: true }),

  requestPasswordReset: (email: string) =>
    api.post<{ detail: string; debug_token?: string }>(
      "/auth/password/reset/",
      { email },
      { skipAuth: true, skipTenant: true },
    ),
  confirmPasswordReset: (token: string, new_password: string) =>
    api.post<{ detail: string }>(
      "/auth/password/reset/confirm/",
      { token, new_password },
      { skipAuth: true, skipTenant: true },
    ),

  logout: (refresh: string) => api.post<void>("/auth/logout/", { refresh }, { skipTenant: true }),

  me: () => api.get<User>("/auth/me/", { skipTenant: true }),
};

export function isMfaRequired(res: AuthTokens | MfaRequired): res is MfaRequired {
  return "mfa_required" in res && res.mfa_required === true;
}

// ---------------------------------------------------------------- OAuth (social)
export type OAuthProvider = "google" | "apple";

export const oauthApi = {
  /** Begin the PKCE flow: returns the provider URL to send the browser to.
   * A 400 means the provider isn't configured on this deployment. */
  authorize: (provider: OAuthProvider) =>
    api.get<{ authorization_url: string }>(`/auth/oauth/${provider}/authorize/`, {
      skipAuth: true,
      skipTenant: true,
    }),

  /** Complete the flow after the provider redirects back with code + state. */
  callback: (provider: OAuthProvider, payload: { code: string; state: string }) =>
    api.post<AuthTokens | MfaRequired>(`/auth/oauth/${provider}/callback/`, payload, {
      skipAuth: true,
      skipTenant: true,
    }),
};

// ---------------------------------------------------------------- WebAuthn (passkeys)
/** Options objects are opaque WebAuthn JSON (base64url-encoded), passed straight
 * to @simplewebauthn/browser. `state` (auth) rides alongside and is echoed back. */
export const webauthnApi = {
  authOptions: (email?: string) =>
    api.post<Record<string, unknown> & { state: string }>(
      "/auth/webauthn/authenticate/options/",
      { email: email || "" },
      { skipAuth: true, skipTenant: true },
    ),

  authVerify: (payload: { state: string; credential: unknown }) =>
    api.post<AuthTokens | MfaRequired>("/auth/webauthn/authenticate/verify/", payload, {
      skipAuth: true,
      skipTenant: true,
    }),

  registerOptions: () =>
    api.post<Record<string, unknown>>("/auth/webauthn/register/options/", undefined, { skipTenant: true }),

  registerVerify: (payload: { credential: unknown; device_name?: string }) =>
    api.post<WebAuthnCredential>("/auth/webauthn/register/verify/", payload, { skipTenant: true }),

  listCredentials: () => api.get<WebAuthnCredential[]>("/auth/webauthn/credentials/", { skipTenant: true }),

  deleteCredential: (id: string) =>
    api.delete<void>(`/auth/webauthn/credentials/${id}/`, { skipTenant: true }),
};

// ---------------------------------------------------------------- profile & MFA
export const profileApi = {
  update: (payload: { first_name?: string; last_name?: string }) =>
    api.patch<User>("/auth/me/", payload, { skipTenant: true }),
};

export const mfaApi = {
  enrollTotp: () => api.post<TotpEnrollment>("/auth/mfa/totp/enroll/", undefined, { skipTenant: true }),
  confirmTotp: (code: string) =>
    api.post<{ backup_codes: string[] }>("/auth/mfa/totp/confirm/", { code }, { skipTenant: true }),
  disableTotp: (code: string) => api.post<void>("/auth/mfa/totp/disable/", { code }, { skipTenant: true }),
  regenerateBackupCodes: (code: string) =>
    api.post<{ backup_codes: string[] }>("/auth/mfa/backup-codes/regenerate/", { code }, { skipTenant: true }),
};
