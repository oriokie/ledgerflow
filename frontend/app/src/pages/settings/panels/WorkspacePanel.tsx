import { ArrowRight } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { tenancyApi } from "../../../api/tenancy";
import { ApiError } from "../../../api/client";
import { useAuth } from "../../../lib/AuthContext";
import { Badge, Banner, Button, Input, Select, Switch, Text, useToast } from "../../../ui";
import { CURRENCY_OPTIONS } from "../../../lib/currencies";
import { DangerZone, SettingsAdvanced, SettingsRow, SettingsSection } from "../components";

export function WorkspacePanel() {
  const { activeWorkspace } = useAuth();
  const tenant = activeWorkspace?.tenant;
  const isOwner = activeWorkspace?.role === "owner";
  const toast = useToast();
  const [exporting, setExporting] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const [closing, setClosing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const baseCurrency = tenant?.base_currency ?? "USD";
  const [savingCurrency, setSavingCurrency] = useState(false);
  const [savedCurrency, setSavedCurrency] = useState(false);
  const [blockOverdrafts, setBlockOverdrafts] = useState(tenant?.block_overdrafts ?? true);
  const [savingOverdrafts, setSavingOverdrafts] = useState(false);

  /**
   * Saved optimistically and reverted on failure.
   *
   * Unlike the base currency this needs no reload: nothing is cached against
   * it and it only governs what the server will accept from the next posting
   * onward. Anything already recorded stays exactly as it is.
   */
  const saveBlockOverdrafts = async (next: boolean) => {
    if (!tenant) return;
    setBlockOverdrafts(next);
    setSavingOverdrafts(true);
    setError(null);
    try {
      await tenancyApi.updateWorkspace(tenant.id, { block_overdrafts: next });
    } catch (err) {
      setBlockOverdrafts(!next);
      setError(err instanceof ApiError ? err.detail : "Couldn't change that setting.");
    } finally {
      setSavingOverdrafts(false);
    }
  };

  const saveBaseCurrency = async (code: string) => {
    if (!tenant || code === tenant.base_currency) return;
    setSavingCurrency(true);
    setSavedCurrency(false);
    setError(null);
    try {
      await tenancyApi.updateWorkspace(tenant.id, { base_currency: code });
      setSavedCurrency(true);
      // Reload so the new base flows through context + defaults everywhere.
      setTimeout(() => window.location.reload(), 400);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't update the base currency.");
    } finally {
      setSavingCurrency(false);
    }
  };

  const exportData = async () => {
    if (!tenant) return;
    setExporting(true);
    setError(null);
    try {
      const data = await tenancyApi.exportWorkspace(tenant.id);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `ledgerflow-${tenant.name.replace(/\s+/g, "-").toLowerCase()}-export.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast("Your data export has downloaded");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't export your data.");
    } finally {
      setExporting(false);
    }
  };

  const closeWorkspace = async () => {
    if (!tenant) return;
    setClosing(true);
    setError(null);
    try {
      await tenancyApi.closeWorkspace(tenant.id);
      // The workspace is gone; a full reload drops it from context and re-routes.
      window.location.href = "/";
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't close the workspace.");
      setClosing(false);
    }
  };

  return (
    <>
      <SettingsSection title="Workspace" description="Details for the workspace you're currently in.">
        <SettingsRow title="Name">
          <Text tone="secondary" size="sm">
            {tenant?.name ?? "—"}
          </Text>
        </SettingsRow>
        <SettingsRow title="Your role">
          <Badge tone="neutral">{activeWorkspace?.role ?? "—"}</Badge>
        </SettingsRow>
        <SettingsRow title="Base currency" description="Reports roll up to this. Existing transactions keep their own currency.">
          {isOwner ? (
            <div style={{ display: "flex", gap: "var(--lf-space-2)", alignItems: "center" }}>
              <Select
                aria-label="Base currency"
                options={CURRENCY_OPTIONS}
                value={baseCurrency}
                onChange={(e) => saveBaseCurrency(e.target.value)}
                disabled={savingCurrency}
              />
              {savedCurrency && (
                <Text tone="secondary" size="sm">
                  Saved
                </Text>
              )}
            </div>
          ) : (
            <Text tone="secondary" size="sm">
              {tenant?.base_currency ?? "—"}
            </Text>
          )}
        </SettingsRow>
        <SettingsRow
          title="Stop me overdrawing an account"
          description="Refuses a payment you enter by hand that an account can't cover. Imports, bank syncs and recurring charges are always recorded — they're reporting what already happened. Credit cards and loans are never affected."
        >
          {isOwner ? (
            <Switch
              checked={blockOverdrafts}
              disabled={savingOverdrafts}
              onChange={(e) => saveBlockOverdrafts(e.target.checked)}
              label={blockOverdrafts ? "On" : "Off"}
              aria-label="Stop me overdrawing an account"
            />
          ) : (
            <Text tone="secondary" size="sm">
              {tenant?.block_overdrafts ? "On" : "Off"}
            </Text>
          )}
        </SettingsRow>
        <SettingsRow title="Locale & time zone">
          <Text tone="secondary" size="sm">
            {tenant?.default_locale ?? "—"} · {tenant?.default_timezone ?? "—"}
          </Text>
        </SettingsRow>
      </SettingsSection>

      <AllWorkspacesSection />

      <SettingsSection title="Manage" description="These open in their own dedicated areas.">
        <Link className="lf-settings-linkcard" to="/members">
          <div>
            <div className="lf-settings-row-title">Members</div>
            <p className="lf-settings-row-desc">Invite people and manage their roles.</p>
          </div>
          <ArrowRight size={16} strokeWidth={1.8} aria-hidden="true" />
        </Link>
        <Link className="lf-settings-linkcard" to="/billing">
          <div>
            <div className="lf-settings-row-title">Billing &amp; plan</div>
            <p className="lf-settings-row-desc">Subscription, payment methods, and invoices.</p>
          </div>
          <ArrowRight size={16} strokeWidth={1.8} aria-hidden="true" />
        </Link>
      </SettingsSection>

      <SettingsSection title="Data & privacy" description="Take a copy of everything in this workspace.">
        <SettingsRow title="Export data" description="Download all of this workspace's data as JSON.">
          <Button variant="secondary" loading={exporting} onClick={exportData}>
            Export
          </Button>
        </SettingsRow>
      </SettingsSection>

      {error && <Banner tone="danger">{error}</Banner>}

      {isOwner && (
        <DangerZone description="Irreversible actions that affect everyone in this workspace.">
          <SettingsAdvanced label="Close this workspace">
            <Banner tone="danger">
              Closing removes this workspace for everyone and schedules its data for deletion. This can't be
              undone from here.
            </Banner>
            <SettingsRow
              title="Confirm"
              description={`Type the workspace name (${tenant?.name}) to confirm.`}
              htmlFor="close-confirm"
            >
              <Input
                id="close-confirm"
                value={confirmName}
                onChange={(e) => setConfirmName(e.target.value)}
                placeholder={tenant?.name}
              />
            </SettingsRow>
            <div>
              <Button
                variant="danger"
                disabled={confirmName !== tenant?.name}
                loading={closing}
                onClick={closeWorkspace}
              >
                Close workspace
              </Button>
            </div>
          </SettingsAdvanced>
        </DangerZone>
      )}
    </>
  );
}

/**
 * Every workspace this account belongs to, renameable and closeable in place.
 *
 * The settings above describe whichever workspace you happen to be *in*, so
 * tidying up a second one meant switching into it first, coming here, and
 * closing it — once per workspace. An account that ended up with nine of them
 * (a retry loop during signup created one per attempt) had no way to see that
 * had happened, let alone fix it.
 *
 * Owner-only actions, matching the API: WorkspaceDetailView refuses a PATCH or
 * DELETE from anyone else, and offering a control that only 403s is worse than
 * not offering it.
 */
function AllWorkspacesSection() {
  const { workspaces: all, activeWorkspace, refreshWorkspaces, switchWorkspace } = useAuth();
  // Tolerates a context that has not finished loading: a settings panel is not
  // worth crashing the whole page over, and one workspace is the same "nothing
  // to manage here" case as none.
  const workspaces = all ?? [];
  const toast = useToast();
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const [closingId, setClosingId] = useState<string | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (workspaces.length < 2) return null;

  const rename = async (tenantId: string) => {
    setBusy(true);
    setError(null);
    try {
      await tenancyApi.updateWorkspace(tenantId, { name: draftName.trim() });
      await refreshWorkspaces();
      setRenamingId(null);
      toast("Workspace renamed");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't rename that workspace.");
    } finally {
      setBusy(false);
    }
  };

  const close = async (tenantId: string) => {
    setBusy(true);
    setError(null);
    try {
      await tenancyApi.closeWorkspace(tenantId);
      // Closing the one you are standing in leaves the shell pointing at
      // something that no longer exists, so that case reloads rather than
      // trying to re-render around the hole.
      if (tenantId === activeWorkspace?.tenant.id) {
        window.location.href = "/";
        return;
      }
      await refreshWorkspaces();
      setClosingId(null);
      setConfirmText("");
      toast("Workspace closed");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't close that workspace.");
      setBusy(false);
    }
  };

  return (
    <SettingsSection
      title="All your workspaces"
      description="Everything this account belongs to. Renaming and closing are limited to the ones you own."
    >
      {error && <Banner tone="danger">{error}</Banner>}

      {workspaces.map((ws) => {
        const isActive = ws.tenant.id === activeWorkspace?.tenant.id;
        const owns = ws.role === "owner";
        return (
          <SettingsRow
            key={ws.tenant.id}
            title={ws.tenant.name}
            description={`${ws.tenant.base_currency} · ${ws.role}${isActive ? " · currently open" : ""}`}
          >
            <div style={{ display: "flex", gap: "var(--lf-space-2)", flexWrap: "wrap" }}>
              {!isActive && (
                <Button variant="ghost" onClick={() => switchWorkspace(ws.tenant.id)}>
                  Open
                </Button>
              )}
              {owns && renamingId !== ws.tenant.id && (
                <Button
                  variant="ghost"
                  onClick={() => {
                    setRenamingId(ws.tenant.id);
                    setDraftName(ws.tenant.name);
                    setClosingId(null);
                  }}
                >
                  Rename
                </Button>
              )}
              {owns && closingId !== ws.tenant.id && (
                <Button
                  variant="ghost"
                  onClick={() => {
                    setClosingId(ws.tenant.id);
                    setConfirmText("");
                    setRenamingId(null);
                  }}
                >
                  Close
                </Button>
              )}
            </div>
          </SettingsRow>
        );
      })}

      {renamingId && (
        <SettingsRow title="New name" htmlFor="ws-rename">
          <div style={{ display: "flex", gap: "var(--lf-space-2)" }}>
            <Input
              id="ws-rename"
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
            />
            <Button
              variant="primary"
              loading={busy}
              disabled={!draftName.trim()}
              onClick={() => rename(renamingId)}
            >
              Save
            </Button>
            <Button variant="ghost" onClick={() => setRenamingId(null)}>
              Cancel
            </Button>
          </div>
        </SettingsRow>
      )}

      {closingId && (
        <>
          <Banner tone="danger">
            Closing removes this workspace for everyone in it and schedules its data for deletion.
            This can't be undone from here.
          </Banner>
          <SettingsRow
            title="Confirm"
            description={`Type ${workspaces.find((w) => w.tenant.id === closingId)?.tenant.name} to confirm.`}
            htmlFor="ws-close-confirm"
          >
            <div style={{ display: "flex", gap: "var(--lf-space-2)" }}>
              <Input
                id="ws-close-confirm"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                placeholder={workspaces.find((w) => w.tenant.id === closingId)?.tenant.name}
              />
              <Button
                variant="danger"
                loading={busy}
                disabled={
                  confirmText !== workspaces.find((w) => w.tenant.id === closingId)?.tenant.name
                }
                onClick={() => close(closingId)}
              >
                Close workspace
              </Button>
              <Button variant="ghost" onClick={() => setClosingId(null)}>
                Cancel
              </Button>
            </div>
          </SettingsRow>
        </>
      )}
    </SettingsSection>
  );
}
