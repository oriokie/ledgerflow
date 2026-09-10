import { useState } from "react";
import { Link } from "react-router-dom";
import { Inbox, Search } from "lucide-react";

import { ApiError } from "../../api/client";
import type { UserAccountStatus } from "../../api/platform";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import { ReasonDialog } from "../../components/admin/AdminShell";
import {
  useCapability,
  useLookupUser,
  usePlatformMe,
  useUserRecoveryAction,
  type UserRecoveryAction,
} from "../../hooks/usePlatform";
import {
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  Input,
  Stack,
  Text,
  useToast,
} from "../../ui";
import { moment } from "./format";

const ACTION_COPY: Record<
  UserRecoveryAction,
  { label: string; title: string; confirm: string; description: string; destructive?: boolean }
> = {
  reactivate: {
    label: "Reactivate",
    title: "Reactivate this account",
    confirm: "Reactivate",
    description: "Restores sign-in. Does not unsuspend a workspace that is past due.",
  },
  deactivate: {
    label: "Deactivate",
    title: "Deactivate this account",
    confirm: "Deactivate",
    description: "They will not be able to sign in until the account is reactivated.",
    destructive: true,
  },
  "send-password-reset": {
    label: "Send password reset",
    title: "Send a password reset",
    confirm: "Send link",
    description: "Sends a short-lived link to their email. Staff never set a password.",
  },
  "reset-mfa": {
    label: "Reset two-factor",
    title: "Reset two-factor authentication",
    confirm: "Reset MFA",
    description:
      "Removes their authenticator. This lowers a security control — only do it after you have verified the caller.",
    destructive: true,
  },
  "verify-email": {
    label: "Mark email verified",
    title: "Mark the email as verified",
    confirm: "Verify email",
    description: "Clears the unverified-email blocker so they can sign in.",
  },
};

export function AdminUsersPage() {
  const { data: me } = usePlatformMe();
  const can = useCapability(me);
  const lookup = useLookupUser();
  const act = useUserRecoveryAction();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [account, setAccount] = useState<UserAccountStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<UserRecoveryAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const search = async () => {
    setError(null);
    setAccount(null);
    try {
      const result = await lookup.mutateAsync(email.trim());
      setAccount(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not look up that email.");
    }
  };

  const onConfirm = async (reason: string) => {
    if (!account || !pending) return;
    setActionError(null);
    try {
      const next = await act.mutateAsync({ userId: account.user_id, action: pending, reason });
      setAccount(next);
      toast("Account updated", { tone: "success" });
      setPending(null);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.detail : "That action was refused.");
    }
  };

  const actions: UserRecoveryAction[] = [];
  if (can("user.recover")) {
    if (account && !account.is_active) actions.push("reactivate");
    if (account?.is_active) actions.push("deactivate");
    actions.push("send-password-reset");
    if (account && !account.is_verified) actions.push("verify-email");
  }
  if (can("user.mfa_reset") && account?.mfa_enabled) actions.push("reset-mfa");

  return (
    <Stack gap={4}>
      <AdminPageHeader
        title="Users"
        description="Look up a customer account and clear the things that stop them getting in. Staff never set a password."
      />

      <form
        className="lf-admin-toolbar"
        onSubmit={(event) => {
          event.preventDefault();
          void search();
        }}
      >
        <div className="lf-admin-toolbar-search">
          <Input
            label="Email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="customer@example.com"
          />
        </div>
        <Button type="submit" disabled={!email.trim() || lookup.isPending}>
          <Search size={15} strokeWidth={2} aria-hidden />
          Look up
        </Button>
      </form>

      {error && <Banner tone="danger">{error}</Banner>}

      {!account && !error && !lookup.isPending && (
        <Card>
          <EmptyState
            icon={Inbox}
            title="Find an account"
            body="Search by the email they sign in with. The result says plainly why they cannot get in."
          />
        </Card>
      )}

      {account && (
        <Card>
          <Stack gap={3}>
            <div>
              <Text size="sm" tone="tertiary">
                {account.email}
              </Text>
              <p className="lf-admin-user-name">{account.full_name || "No name on file"}</p>
            </div>
            <div className="lf-inline lf-gap-2">
              <Badge tone={account.is_active ? "success" : "danger"}>
                {account.is_active ? "Active" : "Deactivated"}
              </Badge>
              <Badge tone={account.is_verified ? "success" : "warning"}>
                {account.is_verified ? "Email verified" : "Email unverified"}
              </Badge>
              <Badge tone={account.mfa_enabled ? "success" : "neutral"}>
                {account.mfa_enabled ? "2FA on" : "2FA off"}
              </Badge>
            </div>
            {account.blockers.length > 0 && (
              <Banner tone="warning">
                {account.blockers.map((blocker) => (
                  <div key={blocker}>{blocker}</div>
                ))}
              </Banner>
            )}
            <Text size="sm" tone="secondary">
              Last sign-in {account.last_login_at ? moment(account.last_login_at) : "never"}. Account
              created {moment(account.created_at)}.
            </Text>
            {account.workspaces.length > 0 && (
              <ul className="lf-admin-user-workspaces">
                {account.workspaces.map((workspace) => (
                  <li key={workspace.tenant_id}>
                    <Link className="lf-admin-tenant-link" to={`/admin/tenants/${workspace.tenant_id}`}>
                      {workspace.name}
                    </Link>
                    <Text size="sm" tone="tertiary">
                      {workspace.role}
                      {workspace.workspace_active ? "" : " · suspended"}
                    </Text>
                  </li>
                ))}
              </ul>
            )}
            {actions.length > 0 && (
              <div className="lf-inline lf-gap-2">
                {actions.map((action) => (
                  <Button
                    key={action}
                    size="sm"
                    variant={ACTION_COPY[action].destructive ? "ghost" : "secondary"}
                    onClick={() => {
                      setActionError(null);
                      setPending(action);
                    }}
                  >
                    {ACTION_COPY[action].label}
                  </Button>
                ))}
              </div>
            )}
          </Stack>
        </Card>
      )}

      {pending && (
        <ReasonDialog
          open
          title={ACTION_COPY[pending].title}
          confirmLabel={ACTION_COPY[pending].confirm}
          destructive={ACTION_COPY[pending].destructive}
          minLength={10}
          pending={act.isPending}
          error={actionError}
          onClose={() => setPending(null)}
          onConfirm={onConfirm}
          description={ACTION_COPY[pending].description}
        />
      )}
    </Stack>
  );
}
