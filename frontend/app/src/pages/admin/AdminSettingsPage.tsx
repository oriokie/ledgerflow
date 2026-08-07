import { useEffect, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import type { PlatformSetting } from "../../api/platform";
import { useCapability, usePlatformMe, usePlatformSettings, useWriteSetting } from "../../hooks/usePlatform";
import {
  Badge,
  Banner,
  Button,
  Card,
  Input,
  SegmentedControl,
  LoadingBlock,
  Stack,
  Switch,
  Text,
  useToast,
} from "../../ui";
import { AdminPageHeader } from "../../components/admin/AdminPageHeader";
import { ReasonDialog } from "../../components/admin/AdminShell";
import { Illustration, ILLUSTRATION_STYLES } from "../../ui/illustration";

const GROUP_LABELS: Record<string, string> = {
  invoicing: "Invoicing",
  payments: "Payments",
  email: "Outbound email",
  ai: "AI",
  operations: "Operations",
};

/** Fixed display order. Deriving this from whatever groups a given API
 * response happens to include would let the sections reshuffle between
 * visits — GROUP_LABELS is already a fixed sequence, so it doubles as one. */
const GROUP_ORDER = Object.keys(GROUP_LABELS);

/** Groups where a save can rotate a credential or flip a gate that changes
 * what customers can do or where their data goes — the same bar as a Plan
 * edit or a Tenant action, so they go through a reason prompt instead of
 * straight to the API. Left ungated, the backend logs only the generic
 * "Updated {key}.", which is indistinguishable from no audit trail at all. */
const REASON_REQUIRED_GROUPS = new Set(["payments", "email", "ai"]);

const GROUP_NOTES: Record<string, string> = {
  invoicing:
    "Printed on every invoice you issue. Changing these affects documents issued from now on — already-issued invoices keep the details they were created with.",
  payments:
    "Which providers customers can pay with, and their credentials. Prefer setting secrets in the environment; use these fields only when you need to rotate a key without a deploy.",
  email:
    "Where invitations, password resets and invoices are sent from. Leave every field empty to keep using the environment's EMAIL_* values; anything set here overrides them from the next message, with no deploy. A broken relay fails silently, so send yourself a test after changing it.",
  ai: "AI is off unless you turn it on here. This is the first of three gates — a workspace also needs a plan that includes AI, and its owner can still opt out.",
  operations: "Thresholds the health dashboard and support tooling use.",
};

/** Where a value came from, in words an operator can act on. */
function SourceBadge({ setting }: { setting: PlatformSetting }) {
  if (setting.source === "database") return <Badge tone="success">Set here</Badge>;
  if (setting.source === "environment") return <Badge tone="neutral">From environment</Badge>;
  return <Badge tone="neutral">Default</Badge>;
}

/**
 * Both sets, side by side, on the screen where the choice is made.
 *
 * A style setting whose effect you cannot see until you save it and go looking
 * is a setting people change once and then leave alone. The previews force the
 * `style` prop rather than following the platform setting — they are the only
 * place in the product allowed to.
 */
function IllustrationStylePreview({ current }: { current: string }) {
  return (
    <div className="lf-admin-illus-preview">
      {ILLUSTRATION_STYLES.map((style) => (
        <figure key={style} data-current={style === current || undefined}>
          <div>
            {/* `animate` because a picker for an animated set that shows a
                still image is asking the operator to choose blind. */}
            <Illustration name="welcome" size="spot" style={style} animate />
            <Illustration name="secure" size="spot" style={style} animate />
            <Illustration name="no-data" size="spot" style={style} animate />
          </div>
          <figcaption>{style === current ? `${style} — in use` : style}</figcaption>
        </figure>
      ))}
    </div>
  );
}

function SettingRow({
  setting,
  disabled,
  onSave,
}: {
  setting: PlatformSetting;
  disabled: boolean;
  onSave: (key: string, value: unknown, label: string) => Promise<void>;
}) {
  const isSecret = setting.kind === "secret";
  const [draft, setDraft] = useState<string>(
    setting.value === null || setting.value === undefined ? "" : String(setting.value),
  );
  const [dirty, setDirty] = useState(false);

  // Re-sync when the server value changes underneath us (another operator, or
  // our own save landing) — but never clobber an edit in progress.
  useEffect(() => {
    if (!dirty) {
      setDraft(setting.value === null || setting.value === undefined ? "" : String(setting.value));
    }
  }, [setting.value, dirty]);

  const commit = async (value: unknown) => {
    await onSave(setting.key, value, setting.label);
    setDirty(false);
    if (isSecret) setDraft("");
  };

  /* A closed set is a choice, not a text field. Rendering it as an input is
     how somebody types "doodles" and finds out from a blank page. */
  if (setting.choices?.length) {
    const current = setting.value === null || setting.value === undefined ? "" : String(setting.value);
    return (
      <div className="lf-admin-setting">
        <div className="lf-admin-setting-label">
          <strong>{setting.label}</strong>
          <Text size="xs" tone="tertiary">
            {setting.help}
          </Text>
          {setting.key === "appearance.illustration_style" && (
            <IllustrationStylePreview current={current} />
          )}
        </div>
        <div className="lf-admin-setting-control">
          <SourceBadge setting={setting} />
          <SegmentedControl
            legend={setting.label}
            value={current}
            onChange={(next: string) => void commit(next)}
            options={setting.choices.map((c) => ({ value: c, label: c[0].toUpperCase() + c.slice(1) }))}
          />
        </div>
      </div>
    );
  }

  if (setting.kind === "boolean") {
    return (
      <div className="lf-admin-setting">
        <div className="lf-admin-setting-label">
          <strong>{setting.label}</strong>
          <Text size="xs" tone="tertiary">
            {setting.help}
          </Text>
        </div>
        <div className="lf-admin-setting-control">
          <SourceBadge setting={setting} />
          <Switch
            checked={Boolean(setting.value)}
            disabled={disabled}
            label={setting.label}
            onChange={(event) => commit(event.target.checked)}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="lf-admin-setting">
      <div className="lf-admin-setting-label">
        <strong>{setting.label}</strong>
        <Text size="xs" tone="tertiary">
          {setting.help}
        </Text>
        {isSecret && setting.is_set && (
          <Text size="xs" tone="tertiary">
            A value is configured. It cannot be read back — enter a new one to replace it.
          </Text>
        )}
      </div>
      <div className="lf-admin-setting-control">
        <SourceBadge setting={setting} />
        <Input
          type={isSecret ? "password" : setting.kind === "integer" ? "number" : "text"}
          value={draft}
          disabled={disabled}
          placeholder={isSecret && setting.is_set ? "••••••••" : undefined}
          aria-label={setting.label}
          onChange={(event) => {
            setDraft(event.target.value);
            setDirty(true);
          }}
        />
        <Button
          size="sm"
          variant="secondary"
          disabled={disabled || !dirty || draft === ""}
          onClick={() => commit(setting.kind === "integer" ? Number(draft) : draft)}
        >
          Save
        </Button>
        {setting.overridden && (
          <Button
            size="sm"
            variant="ghost"
            disabled={disabled}
            onClick={() => commit(null)}
            title="Remove the stored value and fall back to the environment"
          >
            Reset
          </Button>
        )}
      </div>
    </div>
  );
}

export function AdminSettingsPage() {
  const { data: staff } = usePlatformMe();
  const can = useCapability(staff);
  const { data, isLoading } = usePlatformSettings();
  const write = useWriteSetting();
  const toast = useToast();
  const [error, setError] = useState<string | null>(null);
  const [pendingSave, setPendingSave] = useState<{ key: string; value: unknown; label: string } | null>(
    null,
  );
  const [reasonError, setReasonError] = useState<string | null>(null);
  // The promise callbacks for the save a ReasonDialog is standing in for —
  // a ref because they are invoked at most once and never rendered.
  const pendingResolvers = useRef<{ resolve: () => void; reject: (err: unknown) => void } | null>(null);

  const editable = can("staff.manage");

  if (isLoading && !data) return <LoadingBlock label="Loading settings…" />;

  const settings = data?.settings ?? [];
  const presentGroups = new Set(settings.map((s) => s.group));
  const groups = [
    ...GROUP_ORDER.filter((g) => presentGroups.has(g)),
    ...[...presentGroups].filter((g) => !GROUP_ORDER.includes(g)),
  ];

  const save = async (key: string, value: unknown, reason?: string) => {
    setError(null);
    try {
      const payload: { key: string; value: unknown; reason?: string } = { key, value };
      if (reason) payload.reason = reason;
      await write.mutateAsync(payload);
      toast(value === null ? "Reset to environment value" : "Saved", { tone: "success" });
    } catch (err) {
      const message = err instanceof ApiError ? err.detail : "Could not save.";
      setError(message);
      throw err;
    }
  };

  /** Payments, email and AI saves route through the reason prompt; everything
   * else saves the moment it's changed, as before. Returns a promise that
   * settles once the dialog is confirmed (and the save lands) or cancelled,
   * so SettingRow's own dirty/draft bookkeeping stays correct either way. */
  const requestSave = (group: string) => (key: string, value: unknown, label: string) => {
    if (!REASON_REQUIRED_GROUPS.has(group)) return save(key, value);
    setReasonError(null);
    return new Promise<void>((resolve, reject) => {
      pendingResolvers.current = { resolve, reject };
      setPendingSave({ key, value, label });
    });
  };

  const confirmPendingSave = async (reason: string) => {
    if (!pendingSave) return;
    try {
      await save(pendingSave.key, pendingSave.value, reason);
      pendingResolvers.current?.resolve();
      pendingResolvers.current = null;
      setPendingSave(null);
    } catch (err) {
      setReasonError(err instanceof ApiError ? String(err.detail) : "Could not save.");
      // Leave the dialog open so the operator can retry without redoing the edit.
    }
  };

  const cancelPendingSave = () => {
    pendingResolvers.current?.reject(new Error("Save cancelled"));
    pendingResolvers.current = null;
    setPendingSave(null);
    setReasonError(null);
  };

  return (
    <Stack gap={4}>
      <AdminPageHeader
        title="Settings"
        description="Values set here override the environment. Secrets are write-only — the console can replace a credential but never show you one."
      />

      {!editable && (
        <Banner tone="info">
          You can see how the platform is configured, but changing it needs the access-management
          capability.
        </Banner>
      )}
      {error && <Banner tone="danger">{error}</Banner>}

      {groups.map((group) => (
        <Card key={group} title={GROUP_LABELS[group] ?? group} ruledHeader>
          {GROUP_NOTES[group] && (
            <Text size="sm" tone="secondary">
              {GROUP_NOTES[group]}
            </Text>
          )}
          <div className="lf-admin-settings-list">
            {settings
              .filter((s) => s.group === group)
              .map((setting) => (
                <SettingRow
                  key={setting.key}
                  setting={setting}
                  disabled={!editable || write.isPending}
                  onSave={requestSave(group)}
                />
              ))}
          </div>
        </Card>
      ))}

      <Card title="Who controls what" ruledHeader>
        <Text size="sm" tone="secondary">
          Three questions that are easy to confuse:
        </Text>
        <dl className="lf-admin-policy">
          <dt>Is AI available at all?</dt>
          <dd>
            You decide, here. It is a cost and data-processing decision — where a household&rsquo;s
            financial data gets sent is not a choice any individual member should make on everyone
            else&rsquo;s behalf.
          </dd>
          <dt>Does this workspace get AI?</dt>
          <dd>
            Their plan decides. AI is an entitlement on the subscription, so it is bought at the
            workspace level, not per person.
          </dd>
          <dt>Can a household turn it off?</dt>
          <dd>
            Yes — the workspace owner can opt out in their own settings, even on a plan that
            includes it. Opting out is always available; opting in is not.
          </dd>
        </dl>
      </Card>

      {pendingSave && (
        <ReasonDialog
          open
          title={`Update ${pendingSave.label}`}
          confirmLabel="Save"
          pending={write.isPending}
          error={reasonError}
          onClose={cancelPendingSave}
          onConfirm={confirmPendingSave}
          description="Rotating a credential or changing what customers can use deserves the same justification as any other consequential change here — it's recorded in the audit log."
        />
      )}
    </Stack>
  );
}
