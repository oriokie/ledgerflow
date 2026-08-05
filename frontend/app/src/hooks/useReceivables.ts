import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { receivablesApi } from "../api/receivables";
import { useAuth } from "../lib/AuthContext";

const PREFIX = "receivables";

export function useReceivables() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "list", activeWorkspace?.tenant.id],
    queryFn: () => receivablesApi.list(),
    enabled: !!activeWorkspace,
  });
}

export function useReceivableSummary() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "summary", activeWorkspace?.tenant.id],
    queryFn: () => receivablesApi.summary(),
    enabled: !!activeWorkspace,
  });
}

/** Everything here changes both the list and the headline figures, so they
 * invalidate the whole prefix rather than trying to be surgical about it. */
function useReceivableMutation<TArgs>(fn: (args: TArgs) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [PREFIX] }),
  });
}

export function useCreateReceivable() {
  return useReceivableMutation(receivablesApi.create);
}

export function useUpdateReceivable() {
  return useReceivableMutation(
    ({ id, ...payload }: { id: string } & Parameters<typeof receivablesApi.update>[1]) =>
      receivablesApi.update(id, payload),
  );
}

export function useDeleteReceivable() {
  return useReceivableMutation((id: string) => receivablesApi.remove(id));
}

export function useRecordRepayment() {
  return useReceivableMutation(
    ({ id, ...payload }: { id: string } & Parameters<typeof receivablesApi.recordRepayment>[1]) =>
      receivablesApi.recordRepayment(id, payload),
  );
}

export function useWriteOffReceivable() {
  return useReceivableMutation((id: string) => receivablesApi.writeOff(id));
}
