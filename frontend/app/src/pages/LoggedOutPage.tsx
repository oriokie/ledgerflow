import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AuthLayout, AuthPageHeader } from "../components/auth/AuthLayout";
import { Stack } from "../ui";

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
    <AuthLayout scene="signed-out">
      <Stack gap={4} className="lf-loggedout">
        <span className="lf-loggedout-icon" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
            <path
              d="M6 5h11a2 2 0 0 1 2 2v12H8a2 2 0 0 1-2-2V5z"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
            />
            <path d="M8 5v14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            <path d="M11 9h5M11 13h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </span>
        <AuthPageHeader eyebrow="Nothing moved" title="See you next time">
          Your books are exactly where you left them. Taking you back to the homepage in a
          moment.
        </AuthPageHeader>
        <div className="lf-loggedout-actions">
          <Link className="lf-btn lf-btn--primary" to="/">
            Back to home
          </Link>
          <Link className="lf-btn lf-btn--secondary" to="/login">
            Sign back in
          </Link>
        </div>
      </Stack>
    </AuthLayout>
  );
}
