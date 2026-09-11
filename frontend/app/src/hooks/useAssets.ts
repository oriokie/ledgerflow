import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { assetsApi } from "../api/assets";
import { useAuth } from "../lib/AuthContext";

const PREFIX = "assets";

export function useAssets() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "list", activeWorkspace?.tenant.id],
    queryFn: assetsApi.list,
    enabled: !!activeWorkspace,
  });
}

export function useAssetSummary() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "summary", activeWorkspace?.tenant.id],
    queryFn: assetsApi.summary,
    enabled: !!activeWorkspace,
  });
}

export function useAsset(id: string | null) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "detail", activeWorkspace?.tenant.id, id],
    queryFn: () => assetsApi.retrieve(id!),
    enabled: !!activeWorkspace && !!id,
  });
}

function invalidate(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: [PREFIX] });
  // Property overlays net worth; a new valuation must move the dashboard too.
  queryClient.invalidateQueries({ queryKey: ["net-worth"] });
  queryClient.invalidateQueries({ queryKey: ["net-worth-base"] });
  queryClient.invalidateQueries({ queryKey: ["net-worth-history"] });
}

export function useCreateAsset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: assetsApi.create,
    onSuccess: () => invalidate(queryClient),
  });
}

export function useUpdateAsset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Parameters<typeof assetsApi.update>[1] }) =>
      assetsApi.update(id, payload),
    onSuccess: () => invalidate(queryClient),
  });
}

export function useDeleteAsset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: assetsApi.remove,
    onSuccess: () => invalidate(queryClient),
  });
}

export function useRecordValuation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string;
      payload: Parameters<typeof assetsApi.recordValuation>[1];
    }) => assetsApi.recordValuation(id, payload),
    onSuccess: () => invalidate(queryClient),
  });
}
