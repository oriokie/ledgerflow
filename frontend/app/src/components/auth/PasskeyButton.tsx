import { startAuthentication, browserSupportsWebAuthn, WebAuthnError } from "@simplewebauthn/browser";
import { Fingerprint } from "lucide-react";
import { useState } from "react";
import { ApiError } from "../../api/client";
import { webauthnApi } from "../../api/auth";
import { useAuth } from "../../lib/AuthContext";
import { Banner, Stack } from "../../ui";

/**
 * Passwordless sign-in with a passkey. Runs the full WebAuthn ceremony:
 * fetch a challenge, let the platform authenticator sign it, verify server-side.
 * A verified passkey satisfies MFA on its own, so a success lands the person
 * straight in the app. The button hides itself on browsers without WebAuthn.
 *
 * `email` is optional — omitted, the browser offers a discoverable credential
 * (usernameless) picker; provided, it scopes to that account's passkeys.
 */
export function PasskeyButton({
  email,
  onMfaRequired,
}: {
  email?: string;
  onMfaRequired?: (mfaToken: string) => void;
}) {
  const { completeLogin } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!browserSupportsWebAuthn()) return null;

  const signIn = async () => {
    setError(null);
    setBusy(true);
    try {
      const { state, ...optionsJSON } = await webauthnApi.authOptions(email);
      const credential = await startAuthentication({ optionsJSON: optionsJSON as never });
      const res = await webauthnApi.authVerify({ state, credential });
      const result = await completeLogin(res);
      if (result.status === "mfa_required") {
        onMfaRequired?.(result.mfaToken);
      }
      // On "ok", AuthContext now holds the session; the page's redirect effect
      // (isAuthenticated) takes over.
    } catch (err) {
      setBusy(false);
      if (err instanceof WebAuthnError || (err instanceof DOMException && err.name === "NotAllowedError")) {
        // User dismissed the prompt or no matching passkey — not an error worth shouting about.
        return;
      }
      setError(err instanceof ApiError ? err.detail : "Couldn't sign in with a passkey.");
    }
  };

  return (
    <Stack gap={2}>
      <button type="button" className="lf-social-btn" disabled={busy} aria-busy={busy} onClick={signIn}>
        <Fingerprint size={18} aria-hidden="true" />
        Sign in with a passkey
      </button>
      {error && <Banner tone="danger">{error}</Banner>}
    </Stack>
  );
}
