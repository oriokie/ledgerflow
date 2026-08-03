import { ArrowRight } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { tenancyApi } from "../../../api/tenancy";
import { ApiError } from "../../../api/client";
import { useAuth } from "../../../lib/AuthContext";
import { Badge, Banner, Button, Input, Select, Text, useToast } from "../../../ui";
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
        <SettingsRow title="Locale & time zone">
          <Text tone="secondary" size="sm">
            {tenant?.default_locale ?? "—"} · {tenant?.default_timezone ?? "—"}
          </Text>
        </SettingsRow>
      </SettingsSection>

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
