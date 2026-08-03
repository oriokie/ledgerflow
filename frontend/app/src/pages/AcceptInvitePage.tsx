import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { membersApi } from "../api/tenancy";
import { useAuth } from "../lib/AuthContext";
import { AuthLayout } from "../components/auth/AuthLayout";
import { Banner, Button, Heading, Input, Stack, Text } from "../ui";

/** Landing page for invitation links (/invite?token=…). Requires login first —
 * ProtectedRoute handles the redirect and brings the person back here. */
export function AcceptInvitePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refreshWorkspaces, switchWorkspace } = useAuth();
  const [token, setToken] = useState(params.get("token") ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const accept = async () => {
    setError(null);
    setBusy(true);
    try {
      const membership = (await membersApi.acceptInvitation(token)) as { tenant?: { id: string } };
      await refreshWorkspaces();
      if (membership?.tenant?.id) {
        switchWorkspace(membership.tenant.id);
      } else {
        navigate("/workspaces", { replace: true });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "That invitation couldn't be accepted.");
      setBusy(false);
    }
  };

  return (
    <AuthLayout>
      <Stack gap={4}>
        <div>
          <Heading level={1}>Join a workspace</Heading>
          <Text tone="secondary" size="sm" style={{ marginTop: "var(--lf-space-2)" }}>
            Paste the invitation token from your email (or follow the link that brought you here).
          </Text>
        </div>
        <Input label="Invitation token" value={token} onChange={(e) => setToken(e.target.value)} />
        {error && <Banner tone="danger">{error}</Banner>}
        <Button variant="primary" block onClick={accept} loading={busy} disabled={!token}>
          Join workspace
        </Button>
      </Stack>
    </AuthLayout>
  );
}
