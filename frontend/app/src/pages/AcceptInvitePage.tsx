import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { membersApi } from "../api/tenancy";
import type { InvitationPreview } from "../api/types";
import { useAuth } from "../lib/AuthContext";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { AuthLayout } from "../components/auth/AuthLayout";
import { Banner, Button, Heading, Input, LoadingBlock, Stack, Text } from "../ui";

/** Landing page for invitation links (/invite?token=…). Requires login first —
 * ProtectedRoute handles the redirect and brings the person back here. */
export function AcceptInvitePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refreshWorkspaces, switchWorkspace } = useAuth();
  const [token, setToken] = useState(params.get("token") ?? "");
  const debouncedToken = useDebouncedValue(token, 300);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // What the invite is for, fetched read-only so the person can see it before
  // they commit -- the whole point of a separate peek endpoint.
  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(Boolean(token));
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    if (!debouncedToken) {
      setPreview(null);
      setPreviewError(null);
      setPreviewLoading(false);
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    setPreviewError(null);
    membersApi
      .previewInvitation(debouncedToken)
      .then((data: InvitationPreview) => {
        if (!cancelled) setPreview(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setPreview(null);
        setPreviewError(
          err instanceof ApiError ? err.detail : "This invitation link is invalid or has expired.",
        );
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedToken]);

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
    <AuthLayout illustration="verify">
      <Stack gap={4}>
        <div>
          <Heading level={1}>Join a workspace</Heading>
          <Text tone="secondary" size="sm" style={{ marginTop: "var(--lf-space-2)" }}>
            Paste the invitation token from your email (or follow the link that brought you here).
          </Text>
        </div>
        <Input label="Invitation token" value={token} onChange={(e) => setToken(e.target.value)} />

        {previewLoading && <LoadingBlock label="Looking up your invitation…" />}
        {!previewLoading && previewError && <Banner tone="warning">{previewError}</Banner>}
        {!previewLoading && !previewError && preview && (
          <Banner tone="info">
            You've been invited to join <strong>{preview.workspace_name}</strong> as{" "}
            <strong style={{ textTransform: "capitalize" }}>{preview.role}</strong>
            {preview.invited_by_display ? <>, invited by {preview.invited_by_display}</> : null}.
          </Banner>
        )}

        {error && <Banner tone="danger">{error}</Banner>}
        <Button variant="primary" block onClick={accept} loading={busy} disabled={!token}>
          Join workspace
        </Button>
      </Stack>
    </AuthLayout>
  );
}
