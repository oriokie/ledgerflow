import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { notificationsApi, type NotificationPreferences } from "../../api/notifications";
import { Banner, LoadingBlock, Switch, Text } from "../../ui";

/**
 * Per-type alert preferences.
 *
 * The backend has supported per-type muting since it was written; nothing
 * exposed it, so the only control was a master push toggle. That is the setting
 * people reach for when alerts get noisy, and "everything off" was the only
 * answer available — which loses the bill reminders along with the noise.
 *
 * Two switches per type rather than one tri-state: "show me in the app" and
 * "email me" are genuinely independent wants, and collapsing them into one
 * control forces a user who likes seeing something in-app to also accept it in
 * their inbox.
 */
export function NotificationPreferencesSection() {
  const client = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: notificationsApi.preferences,
  });
  const update = useMutation({
    mutationFn: (body: Partial<NotificationPreferences>) =>
      notificationsApi.updatePreferences(body),
    onSuccess: (fresh) => client.setQueryData(["notification-preferences"], fresh),
  });

  if (isLoading || !data) return <LoadingBlock label="Loading preferences…" />;

  const muted = new Set(data.muted_types);
  const emailChosen = new Set(
    data.email_types.length ? data.email_types : data.email_default_types,
  );

  const toggleMuted = (type: string, show: boolean) => {
    const next = new Set(muted);
    if (show) next.delete(type);
    else next.add(type);
    update.mutate({ muted_types: [...next] });
  };

  const toggleEmail = (type: string, wanted: boolean) => {
    const next = new Set(emailChosen);
    if (wanted) next.add(type);
    else next.delete(type);
    // Sending the resolved list, not the diff: an empty list means "use the
    // defaults", which is not what a user who just switched their last one off
    // intends.
    update.mutate({ email_types: [...next] });
  };

  return (
    <div className="lf-notif-prefs">
      <Switch
        checked={data.email_enabled}
        label="Email me about my money"
        onChange={(e) => update.mutate({ email_enabled: e.target.checked })}
      />
      <Text size="xs" tone="tertiary">
        Off by default. When on, we send only the alerts with a deadline or a cost attached — not
        all of them.
      </Text>

      <Switch
        checked={data.monthly_summary}
        label="Monthly summary"
        onChange={(e) => update.mutate({ monthly_summary: e.target.checked })}
      />
      <Text size="xs" tone="tertiary">
        One email on the 1st with last month&rsquo;s income, spending and net.
      </Text>

      {!data.email_enabled && data.monthly_summary && (
        <Banner tone="info">
          The monthly summary needs email switched on above.
        </Banner>
      )}

      <table className="lf-notif-table">
        <caption className="lf-visually-hidden">Alert preferences by type</caption>
        <thead>
          <tr>
            <th scope="col">Alert</th>
            <th scope="col">In app</th>
            <th scope="col">Email</th>
          </tr>
        </thead>
        <tbody>
          {data.available_types.map(({ value, label }) => (
            <tr key={value}>
              <th scope="row">{label}</th>
              <td>
                <Switch
                  checked={!muted.has(value)}
                  aria-label={`${label} in app`}
                  onChange={(e) => toggleMuted(value, e.target.checked)}
                />
              </td>
              <td>
                <Switch
                  checked={data.email_enabled && !muted.has(value) && emailChosen.has(value)}
                  // Muting a type mutes it everywhere, so the email switch is
                  // meaningless while it is off — disabling says so rather than
                  // letting someone set a preference that will not apply.
                  disabled={!data.email_enabled || muted.has(value)}
                  aria-label={`${label} by email`}
                  onChange={(e) => toggleEmail(value, e.target.checked)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
