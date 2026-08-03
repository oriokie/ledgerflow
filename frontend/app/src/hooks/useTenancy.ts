import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { membersApi } from "../api/tenancy";
import { useAuth } from "../lib/AuthContext";

export function useMembers() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["members", activeWorkspace?.tenant.id],
    queryFn: () => membersApi.list(),
    enabled: !!activeWorkspace,
  });
}

export function useInvitations() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["invitations", activeWorkspace?.tenant.id],
    queryFn: () => membersApi.listInvitations(),
    enabled: !!activeWorkspace,
  });
}

export function useInviteMember() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ email, role }: { email: string; role: string }) => membersApi.invite(email, role),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["invitations"] }),
  });
}

export function useChangeMemberRole() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ membershipId, role }: { membershipId: string; role: string }) =>
      membersApi.changeRole(membershipId, role),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["members"] }),
  });
}

export function useRemoveMember() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: membersApi.remove,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["members"] }),
  });
}

export function useRevokeInvitation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: membersApi.revokeInvitation,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["invitations"] }),
  });
}
