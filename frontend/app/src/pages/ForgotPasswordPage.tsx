import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";
import { authApi } from "../api/auth";
import { AuthLayout, AuthPageHeader } from "../components/auth/AuthLayout";
import { Banner, Button, Input, Stack } from "../ui";

const schema = z.object({ email: z.string().email("Enter a valid email address.") });
type FormValues = z.infer<typeof schema>;

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [devToken, setDevToken] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = handleSubmit(async ({ email }) => {
    // Always resolves the same way whether or not the email exists.
    const res = await authApi.requestPasswordReset(email).catch(() => null);
    setDevToken(res?.debug_token ?? null);
    setSent(true);
  });

  if (sent) {
    return (
      <AuthLayout scene="recover" illustration="recover" footer={<Link to="/login">Back to sign in</Link>}>
        <Stack gap={4}>
          <AuthPageHeader eyebrow="Reset sent" title="Check your email">
            If that address is registered, we&apos;ve sent a link to reset your password. It expires in an hour.
          </AuthPageHeader>
          {devToken && (
            <Banner tone="info">
              Development shortcut:{" "}
              <Link to={`/reset-password?token=${encodeURIComponent(devToken)}`}>open the reset link</Link>.
            </Banner>
          )}
          <button
            type="button"
            className="lf-auth-retry"
            onClick={() => {
              setSent(false);
              setDevToken(null);
            }}
          >
            Wrong address? Try again
          </button>
        </Stack>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout scene="recover" illustration="recover" footer={<Link to="/login">Back to sign in</Link>}>
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          <AuthPageHeader eyebrow="Account recovery" title="Reset your password">
            Enter your account email and we&apos;ll send a link to set a new password.
          </AuthPageHeader>
          <Input
            label="Email"
            type="email"
            autoComplete="email"
            autoFocus
            error={errors.email?.message}
            {...register("email")}
          />
          <Button type="submit" variant="primary" block loading={isSubmitting}>
            Send reset link
          </Button>
        </Stack>
      </form>
    </AuthLayout>
  );
}
