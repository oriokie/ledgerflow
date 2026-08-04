import { api } from "./client";
import type { Workspace, WorkspaceAISettings, WorkspaceAISettingsInput } from "./types";

export const tenancyApi = {
  /** A user's workspaces span tenants by definition, so this call never
   * sends X-Tenant-ID — there isn't one active tenant yet when listing them. */
  listWorkspaces: () => api.get<Workspace[]>("/tenancy/workspaces/", { skipTenant: true }),

  createWorkspace: (payload: {
    name: string;
    type?: string;
    base_currency?: string;
    locale?: string;
    timezone?: string;
  }) => api.post<Workspace>("/tenancy/workspaces/", payload, { skipTenant: true }),

  updateWorkspace: (tenantId: string, payload: { name?: string; base_currency?: string }) =>
    api.patch<{ id: string; name: string; type: string; base_currency: string }>(
      `/tenancy/workspaces/${tenantId}/`,
      payload,
      { skipTenant: true },
    ),
  /** The workspace's own model choice. Owner-only server-side; the key is
   *  write-only, so `api_key_set` is all that ever comes back about it. */
  getAISettings: (tenantId: string) =>
    api.get<WorkspaceAISettings>(`/tenancy/workspaces/${tenantId}/ai/`, { skipTenant: true }),
  setAISettings: (tenantId: string, payload: WorkspaceAISettingsInput) =>
    api.put<WorkspaceAISettings>(`/tenancy/workspaces/${tenantId}/ai/`, payload, { skipTenant: true }),
  exportWorkspace: (tenantId: string) =>
    api.get<Record<string, unknown>>(`/tenancy/workspaces/${tenantId}/export/`, { skipTenant: true }),
  closeWorkspace: (tenantId: string) =>
    api.delete<void>(`/tenancy/workspaces/${tenantId}/`, { skipTenant: true }),
};

// ---------------------------------------------------------------- members & invitations
import type { Invitation, Member } from "./types";

export const membersApi = {
  list: () => api.get<Member[]>("/tenancy/workspaces/members/"),
  changeRole: (membershipId: string, role: string) =>
    api.patch<Member>(`/tenancy/workspaces/members/${membershipId}/`, { role }),
  remove: (membershipId: string) => api.delete<void>(`/tenancy/workspaces/members/${membershipId}/`),

  listInvitations: () => api.get<Invitation[]>("/tenancy/workspaces/invitations/"),
  invite: (email: string, role: string) =>
    api.post<Invitation>("/tenancy/workspaces/invitations/", { email, role }),
  revokeInvitation: (invitationId: string) =>
    api.delete<void>(`/tenancy/workspaces/invitations/${invitationId}/`),

  /** Not tenant-scoped by design — the caller has no membership yet. */
  acceptInvitation: (token: string) =>
    api.post("/tenancy/invitations/accept/", { token }, { skipTenant: true }),
};
