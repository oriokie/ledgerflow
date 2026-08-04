import { api } from "./client";
import type { Notification, Paginated } from "./types";

export interface NotificationPreferences {
  muted_types: string[];
  email_enabled: boolean;
  email_types: string[];
  push_enabled: boolean;
  monthly_summary: boolean;
  weekly_digest: boolean;
  budget_threshold: number;
  low_balance_minor: number | null;
  large_transaction_minor: number | null;
  /** Ships with the payload so the UI never hard-codes a list that can drift. */
  available_types: { value: string; label: string }[];
  email_default_types: string[];
}

export const notificationsApi = {
  preferences: () => api.get<NotificationPreferences>("/notifications/preferences/"),
  updatePreferences: (body: Partial<NotificationPreferences>) =>
    api.patch<NotificationPreferences>("/notifications/preferences/", body),
  inbox: (unreadOnly = false) =>
    api.get<Paginated<Notification> & { unread_count: number }>(
      `/notifications/${unreadOnly ? "?unread=true" : ""}`,
    ),
  markRead: (id: string) => api.post<Notification>(`/notifications/${id}/read/`),
  markAllRead: () => api.post<{ marked_read: number }>("/notifications/read-all/"),
};
