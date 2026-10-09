import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { authApi } from "../api/auth";
import { AuthLayout, AuthPageHeader } from "../components/auth/AuthLayout";
import { Banner, Stack } from "../ui";

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"idle" | "ok" | "error">("idle");
  const [detail, setDetail] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setState("error");
      setDetail("This verification link is missing or malformed.");
      return;
    }
    authApi
      .confirmEmailVerification(token)
      .then(() => setState("ok"))
      .catch(() => {
        setState("error");
        setDetail("This verification link is invalid or has expired.");
      });
  }, [token]);

  return (
    <AuthLayout scene="recover" footer={<Link to="/login">Back to sign in</Link>}>
      <Stack gap={4}>
        {state === "ok" ? (
          <AuthPageHeader eyebrow="Verified" title="Your email is confirmed">
            You can keep using LedgerFlow. Thank you for confirming the address.
          </AuthPageHeader>
        ) : (
          <AuthPageHeader eyebrow="Verify email" title={state === "error" ? "Could not verify" : "Confirming…"}>
            {detail ?? "One moment."}
          </AuthPageHeader>
        )}
        {state === "error" && <Banner tone="danger">{detail}</Banner>}
        <Link className="lf-btn lf-btn--primary lf-btn--block" to="/">
          Continue
        </Link>
      </Stack>
    </AuthLayout>
  );
}
