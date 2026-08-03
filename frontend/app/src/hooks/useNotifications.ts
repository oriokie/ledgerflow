import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { notificationsApi } from "../api/notifications";
import { useAuth } from "../lib/AuthContext";

export function useNotifications(unreadOnly = false) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["notifications", activeWorkspace?.tenant.id, unreadOnly],
    queryFn: () => notificationsApi.inbox(unreadOnly),
    enabled: !!activeWorkspace,
    // Alerts are worth a light poll — cheap endpoint, and a bill/budget alert
    // raised by the daily sweep should show up without a manual refresh.
    refetchInterval: 60_000,
  });
}

export function useNotificationCount(): number {
  const { data } = useNotifications(true);
  return data?.unread_count ?? 0;
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
}
