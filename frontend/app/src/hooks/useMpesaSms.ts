import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mpesaSmsApi } from "../api/finance";
import { useAuth } from "../lib/AuthContext";

export function useMpesaSmsCaptures() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["mpesa-sms", activeWorkspace?.tenant.id],
    queryFn: () => mpesaSmsApi.list(),
    enabled: !!activeWorkspace,
  });
}

export function useCaptureMpesaSms() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: mpesaSmsApi.capture,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mpesa-sms"] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
    },
  });
}
