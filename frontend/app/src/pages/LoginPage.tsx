import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";
import { ApiError } from "../api/client";
import { useAuth } from "../lib/AuthContext";
import { AuthDivider, AuthLayout } from "../components/auth/AuthLayout";
import { PasskeyButton } from "../components/auth/PasskeyButton";
import { SocialAuthButtons } from "../components/auth/SocialAuthButtons";
import { Banner, Button, Heading, Input, PasswordInput, Stack, Text } from "../ui";

const credentialsSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  password: z.string().min(1, "Password is required."),
});
type CredentialsForm = z.infer<typeof credentialsSchema>;

const mfaSchema = z.object({
  code: z.string().min(6, "Enter your 6-digit code or a backup code."),
});
type MfaForm = z.infer<typeof mfaSchema>;

export function LoginPage() {
  const { isAuthenticated, login, verifyMfa } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mfaToken, setMfaToken] = useState<string | null>(
    (location.state as { mfaToken?: string } | null)?.mfaToken ?? null,
  );
  const [serverError, setServerError] = useState<string | null>(null);

  const credentialsForm = useForm<CredentialsForm>({ resolver: zodResolver(credentialsSchema) });
  const mfaForm = useForm<MfaForm>({ resolver: zodResolver(mfaSchema) });
  const email = credentialsForm.watch("email");

  // Captured once so the deep link ProtectedRoute stashed in location.state
  // (e.g. an invite link) survives both the password step and the MFA step
  // instead of being dropped in favor of the dashboard. The full pathname +
  // search + hash, not just pathname — an invite link is /invite?token=…,
  // and dropping the query string strands the invitee on a bare /invite with
  // no token once they've logged in.
  const fromLocation = (location.state as { from?: Location })?.from;
  const from = fromLocation
    ? `${fromLocation.pathname}${fromLocation.search}${fromLocation.hash}`
    : "/";

  if (isAuthenticated) {
    return <Navigate to={from} replace />;
  }

  const onSubmitCredentials = credentialsForm.handleSubmit(async ({ email, password }) => {
    setServerError(null);
    try {
      const result = await login(email, password);
      if (result.status === "mfa_required") {
        setMfaToken(result.mfaToken);
      } else {
        navigate(from, { replace: true });
      }
    } catch (err) {
      setServerError(err instanceof ApiError ? err.detail : "Something went wrong. Please try again.");
    }
  });

  const onSubmitMfa = mfaForm.handleSubmit(async ({ code }) => {
    if (!mfaToken) return;
    setServerError(null);
    try {
      await verifyMfa(mfaToken, code);
      navigate(from, { replace: true });
    } catch (err) {
      setServerError(err instanceof ApiError ? err.detail : "Invalid code. Please try again.");
    }
  });

  // ---- Second factor step ----
  if (mfaToken) {
    return (
      <AuthLayout>
        <form onSubmit={onSubmitMfa} noValidate>
          <Stack gap={4}>
            <div>
              <Heading level={1}>Verify it&rsquo;s you</Heading>
              <Text tone="secondary" size="sm" style={{ marginTop: "var(--lf-space-2)" }}>
                Enter the 6-digit code from your authenticator app, or a backup code.
              </Text>
            </div>

            <Input
              label="Verification code"
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              error={mfaForm.formState.errors.code?.message}
              {...mfaForm.register("code")}
            />

            {serverError && <Banner tone="danger">{serverError}</Banner>}

            <Stack gap={2} align="stretch">
              <Button type="submit" variant="primary" block loading={mfaForm.formState.isSubmitting}>
                Verify
              </Button>
              <Button
                type="button"
                variant="ghost"
                block
                onClick={() => {
                  setMfaToken(null);
                  setServerError(null);
                }}
              >
                Back
              </Button>
            </Stack>
          </Stack>
        </form>
      </AuthLayout>
    );
  }

  // ---- Credentials step ----
  return (
    <AuthLayout footer={<>New to LedgerFlow? <Link to="/register">Create an account</Link></>}>
      <form onSubmit={onSubmitCredentials} noValidate>
        <Stack gap={4}>
          <div>
            <Heading level={1} className="lf-auth-title">
              Welcome back!
            </Heading>
            <Text size="sm" tone="secondary" style={{ marginTop: "var(--lf-space-3)" }}>
              Your ledger is where you left it. Sign in to pick up the thread.
            </Text>
          </div>

          {(location.state as { resetDone?: boolean } | null)?.resetDone && (
            <Banner tone="success">Your password has been reset. Sign in with your new password.</Banner>
          )}

          <Input
            label="Email"
            type="email"
            autoComplete="email"
            autoFocus
            error={credentialsForm.formState.errors.email?.message}
            {...credentialsForm.register("email")}
          />

          <PasswordInput
            label="Password"
            autoComplete="current-password"
            error={credentialsForm.formState.errors.password?.message}
            {...credentialsForm.register("password")}
          />

          <Text tone="secondary" size="sm">
            You&rsquo;ll stay signed in on this device for 14 days.
          </Text>

          <div style={{ marginTop: "calc(-1 * var(--lf-space-2))", textAlign: "right" }}>
            <Link
              to="/forgot-password"
              className="lf-auth-forgot"
              style={{ fontSize: "var(--lf-text-sm)" }}
            >
              Forgot password?
            </Link>
          </div>

          {serverError && <Banner tone="danger">{serverError}</Banner>}

          <Button type="submit" variant="primary" block loading={credentialsForm.formState.isSubmitting}>
            Log in
          </Button>

          <AuthDivider />

          <PasskeyButton email={email} onMfaRequired={(token) => setMfaToken(token)} />
          <SocialAuthButtons />
        </Stack>
      </form>
    </AuthLayout>
  );
}
