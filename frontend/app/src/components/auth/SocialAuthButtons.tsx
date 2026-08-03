import { useState } from "react";
import { ApiError } from "../../api/client";
import { oauthApi, type OAuthProvider } from "../../api/auth";
import { Banner, Stack } from "../../ui";

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.46 3.44 1.35l2.58-2.58C13.47.9 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z" />
    </svg>
  );
}

function AppleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M17.05 12.94c-.03-2.75 2.25-4.07 2.35-4.13-1.28-1.87-3.27-2.13-3.98-2.16-1.7-.17-3.31 1-4.17 1-.86 0-2.19-.98-3.6-.95-1.85.03-3.56 1.08-4.51 2.73-1.92 3.34-.49 8.28 1.38 10.99.91 1.33 2 2.81 3.42 2.76 1.37-.06 1.89-.89 3.55-.89 1.65 0 2.12.89 3.57.86 1.47-.03 2.41-1.35 3.31-2.68 1.04-1.54 1.47-3.03 1.5-3.11-.03-.01-2.88-1.1-2.91-4.37zM14.3 4.87c.76-.92 1.27-2.2 1.13-3.47-1.09.04-2.41.72-3.19 1.64-.7.81-1.31 2.11-1.15 3.35 1.21.1 2.45-.62 3.21-1.52z" />
    </svg>
  );
}

const PROVIDERS: { id: OAuthProvider; label: string; mark: React.ReactNode }[] = [
  { id: "google", label: "Continue with Google", mark: <GoogleMark /> },
  { id: "apple", label: "Continue with Apple", mark: <AppleMark /> },
];

/**
 * Google / Apple sign-in. Each button starts the real PKCE flow via the
 * authorize endpoint and hands the browser to the provider. If a provider isn't
 * configured on this deployment the endpoint returns 400, and we surface a calm
 * inline note instead of a broken redirect.
 */
export function SocialAuthButtons({ disabled }: { disabled?: boolean }) {
  const [busy, setBusy] = useState<OAuthProvider | null>(null);
  const [error, setError] = useState<string | null>(null);

  const start = async (provider: OAuthProvider) => {
    setError(null);
    setBusy(provider);
    try {
      const { authorization_url } = await oauthApi.authorize(provider);
      // Remember which provider we're mid-flow with so the callback knows.
      sessionStorage.setItem("lf_oauth_provider", provider);
      window.location.href = authorization_url;
    } catch (err) {
      setBusy(null);
      const label = provider === "google" ? "Google" : "Apple";
      setError(
        err instanceof ApiError && err.status === 400
          ? `${label} sign-in isn't available right now.`
          : `Couldn't start ${label} sign-in. Please try again.`,
      );
    }
  };

  return (
    <Stack gap={2}>
      {PROVIDERS.map((p) => (
        <button
          key={p.id}
          type="button"
          className="lf-social-btn"
          disabled={disabled || busy !== null}
          aria-busy={busy === p.id}
          onClick={() => start(p.id)}
        >
          {p.mark}
          {p.label}
        </button>
      ))}
      {error && <Banner tone="info">{error}</Banner>}
    </Stack>
  );
}
