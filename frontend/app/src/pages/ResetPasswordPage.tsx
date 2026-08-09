import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { z } from "zod";
import { authApi } from "../api/auth";
import { ApiError } from "../api/client";
import { AuthLayout } from "../components/auth/AuthLayout";
import { PasswordStrengthMeter } from "../components/auth/PasswordStrengthMeter";
import { Banner, Button, Heading, PasswordInput, Stack, Text } from "../ui";

const schema = z.object({
  new_password: z.string().min(12, "Password must be at least 12 characters."),
});
type FormValues = z.infer<typeof schema>;

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });
  const password = watch("new_password") ?? "";

  if (!token) {
    return (
      <AuthLayout footer={<Link to="/login">Back to sign in</Link>} illustration="recover">
        <Stack gap={4}>
          <Heading level={1}>Link expired or invalid</Heading>
          <Text tone="secondary">This reset link is missing or malformed. Request a new one to continue.</Text>
          <Link className="lf-btn lf-btn--primary" to="/forgot-password">
            Request a new link
          </Link>
        </Stack>
      </AuthLayout>
    );
  }

  const onSubmit = handleSubmit(async ({ new_password }) => {
    setServerError(null);
    try {
      await authApi.confirmPasswordReset(token, new_password);
      navigate("/login", { replace: true, state: { resetDone: true } });
    } catch (err) {
      setServerError(
        err instanceof ApiError ? err.detail : "Couldn't reset your password. The link may have expired.",
      );
    }
  });

  return (
    <AuthLayout footer={<Link to="/login">Back to sign in</Link>} illustration="recover">
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          <Heading level={1}>Choose a new password</Heading>
          <div>
            <PasswordInput
              label="New password"
              autoComplete="new-password"
              hint={password ? undefined : "At least 12 characters."}
              error={errors.new_password?.message}
              {...register("new_password")}
            />
            <div style={{ marginTop: "var(--lf-space-2)" }}>
              <PasswordStrengthMeter password={password} />
            </div>
          </div>
          {serverError && <Banner tone="danger">{serverError}</Banner>}
          <Button type="submit" variant="primary" block loading={isSubmitting}>
            Reset password
          </Button>
        </Stack>
      </form>
    </AuthLayout>
  );
}
