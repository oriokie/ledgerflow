import { UserPlus, X } from "lucide-react";
import { useState } from "react";
import { ApiError } from "../api/client";
import type { Invitation, Member } from "../api/types";
import {
  useChangeMemberRole,
  useInvitations,
  useInviteMember,
  useMembers,
  useRemoveMember,
  useRevokeInvitation,
} from "../hooks/useTenancy";
import { useAuth } from "../lib/AuthContext";
import { formatDateLong } from "../lib/money";
import {
  Badge,
  Banner,
  Button,
  ConfirmAction,
  Heading,
  IconButton,
  Input,
  Modal,
  PageHeader,
  Select,
  Stack,
  Table,
  Text,
  useToast,
} from "../ui";
import type { Column } from "../ui";

const ROLES = ["owner", "admin", "member", "viewer"];

export function MembersPage() {
  const { user, activeWorkspace } = useAuth();
  const { data: members } = useMembers();
  const { data: invitations } = useInvitations();
  const invite = useInviteMember();
  const changeRole = useChangeMemberRole();
  const removeMember = useRemoveMember();
  const revoke = useRevokeInvitation();

  const toast = useToast();

  const [showInvite, setShowInvite] = useState(false);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");
  const [error, setError] = useState<string | null>(null);
  // Separate from `error` above: that one lives inside the invite modal and
  // clears when it closes. Role changes, removals, and revokes happen out in
  // the tables, so a failure there gets its own banner that stays visible.
  const [actionError, setActionError] = useState<string | null>(null);

  const myRole = activeWorkspace?.role ?? "viewer";
  const canManage = myRole === "owner" || myRole === "admin";

  const onInvite = async () => {
    setError(null);
    if (!email.includes("@")) return setError("Enter a valid email.");
    try {
      await invite.mutateAsync({ email, role });
      setEmail("");
      setShowInvite(false);
      toast(`Invitation sent to ${email}.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't send that invitation.");
    }
  };

  const memberColumns: Column<Member>[] = [
    {
      key: "member",
      header: "Member",
      render: (m) => (
        <>
          <span className="lf-cell-primary">{m.full_name || m.email}</span>
          <br />
          <span className="lf-cell-meta">{m.email}</span>
        </>
      ),
    },
    {
      key: "role",
      header: "Role",
      render: (m) =>
        canManage && m.user_id !== user?.id ? (
          <select
            className="lf-select"
            value={m.role}
            aria-label={`Role for ${m.email}`}
            onChange={(e) => {
              const nextRole = e.target.value;
              const name = m.full_name || m.email;
              setActionError(null);
              changeRole.mutate(
                { membershipId: m.id, role: nextRole },
                {
                  onSuccess: () => toast(`${name}'s role changed to ${nextRole}.`),
                  onError: (err) => {
                    setActionError(err instanceof ApiError ? err.detail : `Couldn't change ${name}'s role.`);
                  },
                },
              );
            }}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        ) : (
          <Badge tone="neutral">{m.role}</Badge>
        ),
    },
    {
      key: "joined",
      header: "Joined",
      hideMobile: true,
      render: (m) => <span className="lf-cell-meta">{formatDateLong(m.created_at)}</span>,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (m) =>
        canManage && m.user_id !== user?.id ? (
          <ConfirmAction
            label="Remove"
            confirmLabel="Remove member"
            cancelLabel="Keep"
            disabled={removeMember.isPending}
            onConfirm={async () => {
              const name = m.full_name || m.email;
              setActionError(null);
              try {
                await removeMember.mutateAsync(m.id);
                toast(`Removed ${name} from the workspace.`);
              } catch (err) {
                setActionError(err instanceof ApiError ? err.detail : `Couldn't remove ${name}.`);
              }
            }}
          />
        ) : null,
    },
  ];

  const inviteColumns: Column<Invitation>[] = [
    { key: "email", header: "Email", render: (inv) => inv.email },
    { key: "role", header: "Role", render: (inv) => <Badge tone="neutral">{inv.role}</Badge> },
    {
      key: "by",
      header: "Invited by",
      hideMobile: true,
      render: (inv) => <span className="lf-cell-meta">{inv.invited_by_email ?? "—"}</span>,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (inv) =>
        canManage ? (
          <IconButton
            label={`Revoke invitation for ${inv.email}`}
            icon={<X size={15} />}
            disabled={revoke.isPending}
            onClick={() => {
              setActionError(null);
              revoke.mutate(inv.id, {
                onSuccess: () => toast(`Invitation to ${inv.email} revoked.`),
                onError: (err) => {
                  setActionError(err instanceof ApiError ? err.detail : `Couldn't revoke the invitation for ${inv.email}.`);
                },
              });
            }}
          />
        ) : null,
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title="Members"
        description={
          activeWorkspace?.tenant.name
            ? `Who can see and change ${activeWorkspace.tenant.name}.`
            : "Who can see and change this workspace."
        }
        illustration="together"
        actions={
          canManage ? (
            <Button variant="primary" icon={<UserPlus size={15} />} onClick={() => setShowInvite(true)}>
              Invite
            </Button>
          ) : undefined
        }
      />

      {actionError && (
        <div style={{ marginBottom: "var(--lf-space-4)" }}>
          <Banner tone="danger">{actionError}</Banner>
        </div>
      )}

      <div style={{ marginBottom: "var(--lf-space-8)" }}>
        <Table columns={memberColumns} rows={members ?? []} rowKey={(m) => m.id} caption="Members" />
      </div>

      {invitations && invitations.length > 0 && (
        <section>
          <Heading level={2}>Pending invitations</Heading>
          <div style={{ marginTop: "var(--lf-space-3)" }}>
            <Table columns={inviteColumns} rows={invitations} rowKey={(inv) => inv.id} caption="Pending invitations" />
          </div>
        </section>
      )}

      <Modal
        open={showInvite}
        onClose={() => setShowInvite(false)}
        title="Invite to workspace"
        footer={
          <Button variant="primary" onClick={onInvite} loading={invite.isPending}>
            Send invitation
          </Button>
        }
      >
        <Stack gap={4}>
          <Text tone="tertiary" size="sm">
            They'll get an email with a link; the invitation appears above until accepted.
          </Text>
          <Input
            label="Email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoFocus
          />
          <Select
            label="Role"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            options={[
              { value: "admin", label: "Admin — manage members & all data" },
              { value: "member", label: "Member — read & write financial data" },
              { value: "viewer", label: "Viewer — read-only" },
            ]}
          />
          {error && <Banner tone="danger">{error}</Banner>}
        </Stack>
      </Modal>
    </>
  );
}
