import { LogOut } from "lucide-react";
import { Link } from "react-router-dom";
import { AuthLayout } from "../components/auth/AuthLayout";
import { Heading, Stack, Text } from "../ui";

/**
 * Where logout lands. Instead of dumping people at a login form mid-thought,
 * this closes the session with a calm goodbye — same split shell, same rotating
 * financial wisdom — and one clear way back in.
 */
export function LoggedOutPage() {
  return (
    <AuthLayout>
      <Stack gap={4}>
        <div>
          <span className="lf-loggedout-icon" aria-hidden="true">
            <LogOut size={20} strokeWidth={1.8} />
          </span>
          <Heading level={1}>You're signed out</Heading>
        </div>
        <Text tone="secondary">
          Your session is closed and your data stays safe. Come back any time — your workspaces will be right
          where you left them.
        </Text>
        <Link className="lf-btn lf-btn--primary" to="/login" style={{ justifyContent: "center" }}>
          Sign back in
        </Link>
      </Stack>
    </AuthLayout>
  );
}
