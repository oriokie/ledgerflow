import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { insuranceApi } from "../api/insurance";
import { useAuth } from "../lib/AuthContext";

const PREFIX = "insurance";

export function usePolicies() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "list", activeWorkspace?.tenant.id],
    queryFn: insuranceApi.list,
    enabled: !!activeWorkspace,
  });
}

export function useInsuranceSummary() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "summary", activeWorkspace?.tenant.id],
    queryFn: insuranceApi.summary,
    enabled: !!activeWorkspace,
  });
}

export function usePolicy(id: string | null) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "detail", activeWorkspace?.tenant.id, id],
    queryFn: () => insuranceApi.retrieve(id!),
    enabled: !!activeWorkspace && !!id,
  });
}

function invalidate(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: [PREFIX] });
  queryClient.invalidateQueries({ queryKey: ["insights"] });
}

export function useCreatePolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: insuranceApi.create,
    onSuccess: () => invalidate(queryClient),
  });
}

export function useUpdatePolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Parameters<typeof insuranceApi.update>[1] }) =>
      insuranceApi.update(id, payload),
    onSuccess: () => invalidate(queryClient),
  });
}

export function useDeletePolicy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: insuranceApi.remove,
    onSuccess: () => invalidate(queryClient),
  });
}
