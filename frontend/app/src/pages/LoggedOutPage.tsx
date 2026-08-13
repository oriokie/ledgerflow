import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AuthLayout } from "../components/auth/AuthLayout";
import { Heading, Stack, Text } from "../ui";

/**
 * Where logout lands. A calm close, then home — not a login form mid-thought.
 */
export function LoggedOutPage() {
  const navigate = useNavigate();

  useEffect(() => {
    const timer = window.setTimeout(() => navigate("/", { replace: true }), 5000);
    return () => window.clearTimeout(timer);
  }, [navigate]);

  return (
    <AuthLayout scene="signed-out" illustration="path">
      <Stack gap={4} className="lf-loggedout">
        <p className="lf-cmd-eyebrow">Session closed</p>
        <Heading level={1} className="lf-auth-title">
          See you next time
        </Heading>
        <Text tone="secondary">
          Your books are exactly where you left them. Taking you back to the homepage in a
          moment.
        </Text>
        <div className="lf-loggedout-actions">
          <Link className="lf-btn lf-btn--primary" to="/" style={{ justifyContent: "center" }}>
            Back to home
          </Link>
          <Link className="lf-btn lf-btn--ghost" to="/login" style={{ justifyContent: "center" }}>
            Sign back in
          </Link>
        </div>
      </Stack>
    </AuthLayout>
  );
}
