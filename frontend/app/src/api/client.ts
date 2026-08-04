import { tenantStore, tokenStore } from "./tokenStore";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

/**
 * The API wraps every error in a consistent envelope (see
 * apps/common/exceptions.py):
 *   { "error": { "code": "...", "message": "...", "details": {field: [msg]} } }
 * where `details` is present for serializer validation errors.
 *
 * Older/again-possible shapes are also tolerated so a single parser covers
 * everything: bare {"detail": "..."} and bare {field: [msg]}.
 *
 * ApiError normalizes all of them into `.detail` (best single-line message)
 * and `.fieldErrors` (keyed by field, for react-hook-form's setError), so
 * callers never branch on which shape came back.
 */
export class ApiError extends Error {
  status: number;
  detail: string;
  code: string | null;
  fieldErrors: Record<string, string[]>;

  constructor(status: number, body: unknown) {
    const { detail, code, fieldErrors } = ApiError.parse(body);
    super(detail);
    this.status = status;
    this.detail = detail;
    this.code = code;
    this.fieldErrors = fieldErrors;
    this.name = "ApiError";
  }

  private static collectFieldErrors(source: Record<string, unknown>): Record<string, string[]> {
    const fieldErrors: Record<string, string[]> = {};
    for (const [key, value] of Object.entries(source)) {
      if (Array.isArray(value)) fieldErrors[key] = value.map(String);
      else if (typeof value === "string") fieldErrors[key] = [value];
    }
    return fieldErrors;
  }

  private static parse(body: unknown): {
    detail: string;
    code: string | null;
    fieldErrors: Record<string, string[]>;
  } {
    if (body && typeof body === "object") {
      const obj = body as Record<string, unknown>;

      // Preferred: the { error: { code, message, details } } envelope.
      if (obj.error && typeof obj.error === "object") {
        const err = obj.error as Record<string, unknown>;
        const details = (err.details && typeof err.details === "object" ? err.details : {}) as Record<
          string,
          unknown
        >;
        const fieldErrors = ApiError.collectFieldErrors(details);
        const firstField = Object.values(fieldErrors)[0]?.[0];
        // Prefer a specific field message over the stringified dict in `message`.
        const detail = firstField ?? (typeof err.message === "string" ? err.message : "Request failed.");
        return { detail, code: typeof err.code === "string" ? err.code : null, fieldErrors };
      }

      // Fallback: bare {"detail": "..."}.
      if (typeof obj.detail === "string") {
        return { detail: obj.detail, code: null, fieldErrors: {} };
      }

      // Fallback: bare {field: [msg], ...}.
      const fieldErrors = ApiError.collectFieldErrors(obj);
      const firstMessage = Object.values(fieldErrors)[0]?.[0];
      return { detail: firstMessage ?? "Request failed.", code: null, fieldErrors };
    }
    return { detail: "Request failed.", code: null, fieldErrors: {} };
  }
}

let refreshInFlight: Promise<string | null> | null = null;

/** Exchanges the stored refresh token for a new access token. Coalesces
 * concurrent 401s (e.g. several widgets fetching at once) into one refresh
 * call rather than a stampede. */
async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    const refresh = tokenStore.getRefresh();
    if (!refresh) return null;
    try {
      const res = await fetch(`${BASE_URL}/auth/refresh/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh }),
      });
      if (!res.ok) return null;
      const data = (await res.json()) as { access: string; refresh?: string };
      tokenStore.setAccess(data.access);
      // The backend rotates refresh tokens and blacklists the old one on every
      // use (ROTATE_REFRESH_TOKENS + BLACKLIST_AFTER_ROTATION). Discarding the
      // rotated token here is why every session died ~30 minutes after login:
      // the first refresh worked and burned the stored token, the second
      // presented the blacklisted one and was thrown out.
      if (data.refresh) tokenStore.setTokens(data.access, data.refresh);
      return data.access;
    } catch {
      return null;
    }
  })();

  const result = await refreshInFlight;
  refreshInFlight = null;
  return result;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  /** Skip the X-Tenant-ID header (auth/workspace-list endpoints don't need it). */
  skipTenant?: boolean;
  /** Skip the Authorization header (login/register/refresh). */
  skipAuth?: boolean;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}, isRetry = false): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };

  if (!options.skipAuth) {
    const access = tokenStore.getAccess();
    if (access) headers.Authorization = `Bearer ${access}`;
  }
  if (!options.skipTenant) {
    const tenantId = tenantStore.getActive();
    if (tenantId) headers["X-Tenant-ID"] = tenantId;
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  // 401 on an authenticated request: try exactly one silent refresh, then
  // retry the original call once. A second 401 means the session is truly
  // dead — surface it so the app can redirect to /login.
  if (res.status === 401 && !options.skipAuth && !isRetry) {
    const newAccess = await refreshAccessToken();
    if (newAccess) return request<T>(path, options, true);
    tokenStore.clear();
    tenantStore.clear();
    window.dispatchEvent(new CustomEvent("lf:session-expired"));
    throw new ApiError(401, { detail: "Session expired." });
  }

  // 204 means "nothing here", which is an *answer*, not a failure. It must be
  // a value the caller can hold: TanStack Query rejects a query function that
  // resolves to `undefined` ("Query data cannot be undefined"), so returning
  // undefined here turned every legitimately-empty endpoint — an unfunded
  // portfolio, a debt-free workspace — into a page-level error.
  //
  // `null` is the honest representation and the one the API modules already
  // declare (`Promise<PortfolioSummary | null>`). Callers that ignore the body
  // entirely (DELETE, and other void endpoints) are unaffected.
  if (res.status === 204) return null as T;

  const contentType = res.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json") ? await res.json() : await res.text();

  if (!res.ok) throw new ApiError(res.status, payload);
  return payload as T;
}

/** Auth + tenant headers for non-JSON requests (file upload/download). */
function authHeaders(base: Record<string, string> = {}): Record<string, string> {
  const headers = { ...base };
  const access = tokenStore.getAccess();
  if (access) headers.Authorization = `Bearer ${access}`;
  const tenantId = tenantStore.getActive();
  if (tenantId) headers["X-Tenant-ID"] = tenantId;
  return headers;
}

/** POST multipart form data (file uploads) with auth + one silent refresh. */
export async function postForm<T>(path: string, form: FormData, isRetry = false): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, { method: "POST", headers: authHeaders(), body: form });
  if (res.status === 401 && !isRetry) {
    const newAccess = await refreshAccessToken();
    if (newAccess) return postForm<T>(path, form, true);
    tokenStore.clear();
    tenantStore.clear();
    window.dispatchEvent(new CustomEvent("lf:session-expired"));
    throw new ApiError(401, { detail: "Session expired." });
  }
  const contentType = res.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) throw new ApiError(res.status, payload);
  return payload as T;
}

/** GET a binary resource (e.g. a receipt) as a Blob, with auth + one refresh. */
export async function getBlob(path: string, isRetry = false): Promise<Blob> {
  const res = await fetch(`${BASE_URL}${path}`, { method: "GET", headers: authHeaders() });
  if (res.status === 401 && !isRetry) {
    const newAccess = await refreshAccessToken();
    if (newAccess) return getBlob(path, true);
    tokenStore.clear();
    tenantStore.clear();
    window.dispatchEvent(new CustomEvent("lf:session-expired"));
    throw new ApiError(401, { detail: "Session expired." });
  }
  if (!res.ok) {
    const contentType = res.headers.get("content-type") ?? "";
    const payload = contentType.includes("application/json") ? await res.json() : await res.text();
    throw new ApiError(res.status, payload);
  }
  return res.blob();
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "PATCH", body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "PUT", body }),
  delete: <T>(path: string, options?: Omit<RequestOptions, "method" | "body">) =>
    request<T>(path, { ...options, method: "DELETE" }),
};

export { BASE_URL };
