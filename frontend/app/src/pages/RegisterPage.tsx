import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { z } from "zod";
import { authApi } from "../api/auth";
import { ApiError } from "../api/client";
import { useAuth } from "../lib/AuthContext";
import { AuthDivider, AuthLayout } from "../components/auth/AuthLayout";
import { PasswordStrengthMeter } from "../components/auth/PasswordStrengthMeter";
import { SocialAuthButtons } from "../components/auth/SocialAuthButtons";
import { Banner, Button, Grid, Heading, Input, PasswordInput, Stack } from "../ui";

const schema = z.object({
  first_name: z.string().min(1, "First name is required."),
  last_name: z.string().min(1, "Last name is required."),
  email: z.string().email("Enter a valid email address."),
  // Mirrors the backend's Django password validators (min length 12); the
  // full validator set (common-password, similarity, etc.) still runs
  // server-side and surfaces via ApiError.fieldErrors if it rejects it.
  password: z.string().min(12, "Password must be at least 12 characters."),
});
type FormValues = z.infer<typeof schema>;

export function RegisterPage() {
  const { isAuthenticated, login } = useAuth();
  const navigate = useNavigate();
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });
  const password = watch("password") ?? "";

  if (isAuthenticated) return <Navigate to="/" replace />;

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    try {
      await authApi.register(values);
      // Registration doesn't issue tokens — log in immediately after so the
      // person lands straight in the app rather than back at a login form.
      const result = await login(values.email, values.password);
      if (result.status === "mfa_required") {
        // Fresh accounts have no MFA enrolled yet, so this branch shouldn't
        // occur in practice — but route through login if it somehow does.
        navigate("/login", { replace: true });
        return;
      }
      navigate("/workspaces", { replace: true });
    } catch (err) {
      const formFields: (keyof FormValues)[] = ["email", "password", "first_name", "last_name"];
      let mappedAny = false;
      if (err instanceof ApiError) {
        for (const [field, messages] of Object.entries(err.fieldErrors)) {
          if (formFields.includes(field as keyof FormValues)) {
            setError(field as keyof FormValues, { message: messages[0] });
            mappedAny = true;
          }
        }
      }
      // If nothing mapped to a specific field, show the top-level message.
      if (!mappedAny) {
        setServerError(err instanceof ApiError ? err.detail : "Something went wrong. Please try again.");
      }
    }
  });

  return (
    <AuthLayout footer={<>Already have an account? <Link to="/login">Log in</Link></>}>
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          <Heading level={1}>Create your account</Heading>

          <Grid cols={2} gap={4}>
            <Input
              label="First name"
              autoComplete="given-name"
              error={errors.first_name?.message}
              {...register("first_name")}
            />
            <Input
              label="Last name"
              autoComplete="family-name"
              error={errors.last_name?.message}
              {...register("last_name")}
            />
          </Grid>

          <Input
            label="Email"
            type="email"
            autoComplete="email"
            error={errors.email?.message}
            {...register("email")}
          />

          <div>
            <PasswordInput
              label="Password"
              autoComplete="new-password"
              hint={password ? undefined : "At least 12 characters."}
              error={errors.password?.message}
              {...register("password")}
            />
            <div style={{ marginTop: "var(--lf-space-2)" }}>
              <PasswordStrengthMeter password={password} />
            </div>
          </div>

          {serverError && <Banner tone="danger">{serverError}</Banner>}

          <Button type="submit" variant="primary" block loading={isSubmitting}>
            Create account
          </Button>

          <AuthDivider />

          <SocialAuthButtons />
        </Stack>
      </form>
    </AuthLayout>
  );
}
