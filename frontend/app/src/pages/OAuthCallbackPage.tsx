import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { oauthApi, type OAuthProvider } from "../api/auth";
import { ApiError } from "../api/client";
import { useAuth } from "../lib/AuthContext";
import { AuthLayout } from "../components/auth/AuthLayout";
import { Banner, Button, Heading, LoadingBlock, Stack, Text } from "../ui";

/**
 * Where the OAuth provider redirects back to (matches OAUTH_REDIRECT_URI's path).
 * It reads `code` + `state` from the query, exchanges them for a session, and
 * routes onward. The exchange is guarded so React's double-invoked effects can't
 * spend the single-use PKCE state twice.
 */
export function OAuthCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { completeLogin } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;

    const code = params.get("code");
    const state = params.get("state");
    const providerError = params.get("error"); // e.g. "access_denied" when the user hit "cancel" at the provider
    const providerErrorDescription = params.get("error_description");
    const provider = (sessionStorage.getItem("lf_oauth_provider") as OAuthProvider | null) ?? "google";
    sessionStorage.removeItem("lf_oauth_provider");

    if (providerError) {
      if (providerError === "access_denied") {
        // The user declined consent at the provider - not a failure, no need to alarm them.
        setError("Sign-in was cancelled.");
      } else {
        // Provider-side error (misconfigured client, provider outage, etc.) - distinct from
        // a user decision, so say so and pass along whatever detail the provider gave us.
        setError(
          providerErrorDescription
            ? `Something went wrong with sign-in: ${providerErrorDescription}`
            : "Something went wrong with sign-in. Please try again."
        );
      }
      return;
    }
    if (!code || !state) {
      setError("This sign-in link is incomplete or has expired.");
      return;
    }

    (async () => {
      try {
        const res = await oauthApi.callback(provider, { code, state });
        const result = await completeLogin(res);
        if (result.status === "mfa_required") {
          // Hand the challenge to the login screen's second-factor step.
          navigate("/login", { replace: true, state: { mfaToken: result.mfaToken } });
        } else {
          // ProtectedRoute sends brand-new accounts on to workspace setup.
          navigate("/", { replace: true });
        }
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : "Couldn't complete sign-in. Please try again.");
      }
    })();
  }, [params, completeLogin, navigate]);

  if (error) {
    return (
      <AuthLayout footer={<Link to="/login">Back to login</Link>}>
        <Stack gap={4}>
          <Heading level={1}>Sign-in failed</Heading>
          <Banner tone="danger">{error}</Banner>
          <Button variant="primary" block onClick={() => navigate("/login", { replace: true })}>
            Back to login
          </Button>
        </Stack>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <Stack gap={4} align="center">
        <Heading level={1}>Signing you in…</Heading>
        <Text tone="secondary" size="sm">Completing sign-in with your provider.</Text>
        <LoadingBlock label="Verifying…" />
      </Stack>
    </AuthLayout>
  );
}
