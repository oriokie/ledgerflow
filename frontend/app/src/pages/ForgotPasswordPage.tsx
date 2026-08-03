import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";
import { authApi } from "../api/auth";
import { AuthLayout } from "../components/auth/AuthLayout";
import { Banner, Button, Heading, Input, Stack, Text } from "../ui";

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
      <AuthLayout footer={<Link to="/login">Back to sign in</Link>}>
        <Stack gap={4}>
          <Heading level={1}>Check your email</Heading>
          <Text tone="secondary">
            If that address is registered, we've sent a link to reset your password. It expires in an hour.
          </Text>
          {devToken && (
            <Banner tone="info">
              Development shortcut:{" "}
              <Link to={`/reset-password?token=${encodeURIComponent(devToken)}`}>open the reset link</Link>.
            </Banner>
          )}
        </Stack>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout footer={<Link to="/login">Back to sign in</Link>}>
      <form onSubmit={onSubmit} noValidate>
        <Stack gap={4}>
          <Heading level={1}>Reset your password</Heading>
          <Text tone="secondary">Enter your account email and we'll send you a link to set a new password.</Text>
          <Input label="Email" type="email" autoComplete="email" error={errors.email?.message} {...register("email")} />
          <Button type="submit" variant="primary" block loading={isSubmitting}>
            Send reset link
          </Button>
        </Stack>
      </form>
    </AuthLayout>
  );
}
