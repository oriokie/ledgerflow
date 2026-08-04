import { AlertCircle, CheckCircle2, ExternalLink, HardDrive, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError } from "../../../api/client";
import { tenancyApi } from "../../../api/tenancy";
import type { WorkspaceAISettings } from "../../../api/types";
import { useLLMSettings, useSetTenantAiEnabled } from "../../../hooks/useCoach";
import { useAuth } from "../../../lib/AuthContext";
import { Badge, Banner, Button, Input, Select, Skeleton, Switch, Text } from "../../../ui";
import { SettingsRow, SettingsSection } from "../components";

/**
 * AI configuration.
 *
 * Two halves, and the split is the point. What the *deployment* provides is
 * reported, not edited — it is the operator's cost and vendor decision. What
 * this *workspace* chooses instead is editable, but only by an owner: picking
 * where the household's financial data gets sent is decided for everyone in
 * the household, so it is not a per-member preference.
 *
 * The panel's other job is to answer "I turned it on, why is nothing
 * happening?" — the most common and most silent failure mode here.
 */
export function IntelligencePanel() {
  const { data: settings, isLoading } = useLLMSettings();
  const setTenantAi = useSetTenantAiEnabled();
  const { activeWorkspace } = useAuth();
  const [toggleError, setToggleError] = useState<string | null>(null);

  if (isLoading) return <Skeleton width="60%" />;
  if (!settings) return null;

  const usingLLMInsights = settings.insight_provider.includes("LLMCoach");
  const usingLLMNarration = settings.narrative_provider.includes("LLMNarrator");
  const canToggle = activeWorkspace?.role === "owner" || activeWorkspace?.role === "admin";

  const onToggle = async (checked: boolean) => {
    setToggleError(null);
    try {
      await setTenantAi.mutateAsync(checked);
    } catch {
      setToggleError("Couldn't update this — try again in a moment.");
    }
  };

  return (
    <>
      <SettingsSection
        title="Use AI for this workspace"
        description="The one setting here that's actually yours to control. Turning this off falls back to the built-in, rule-based analysis everywhere — nothing about your data leaves this deployment either way once it's off."
      >
        <SettingsRow
          title="AI-touched insights and narration"
          description={
            canToggle
              ? "Off by default costs nothing — the built-in engine covers everything, all the time."
              : "Ask a workspace owner or admin to change this."
          }
        >
          <Switch
            label=""
            aria-label="Use AI for this workspace"
            checked={settings.tenant_ai_enabled}
            onChange={(event) => onToggle(event.target.checked)}
            disabled={!canToggle || setTenantAi.isPending}
          />
        </SettingsRow>
        {toggleError && <Banner tone="danger">{toggleError}</Banner>}
      </SettingsSection>

      <SettingsSection
        title="AI provider"
        description="LedgerFlow works fully without AI. A model is optional, and adds phrasing and extra suggestions on top of the built-in analysis. This part is set by whoever deploys LedgerFlow, not per workspace — see the note below."
      >
        <SettingsRow title="Status" description="Whether a model can be reached right now.">
          {settings.available ? (
            <Badge tone="success">
              <CheckCircle2 size={13} strokeWidth={2} aria-hidden="true" /> Active
            </Badge>
          ) : (
            <Badge tone="neutral">Not active</Badge>
          )}
        </SettingsRow>

        {/* The whole point of this panel: say what's missing rather than
            leaving the operator to guess. */}
        {!settings.available && settings.reason && (
          <Banner tone="info">
            <AlertCircle size={15} strokeWidth={2} aria-hidden="true" /> {settings.reason}
          </Banner>
        )}

        <SettingsRow title="Provider" description="Set with the LLM_PROVIDER environment variable.">
          <Text as="span">
            {settings.provider_label}
            {settings.is_local && (
              <>
                {" "}
                <Badge tone="neutral">
                  <HardDrive size={12} strokeWidth={2} aria-hidden="true" /> Local
                </Badge>
              </>
            )}
          </Text>
        </SettingsRow>

        <SettingsRow title="Model" description="Set with LLM_MODEL.">
          <Text as="span" tone={settings.model ? "primary" : "tertiary"}>
            {settings.model || "Not set"}
          </Text>
        </SettingsRow>

        <SettingsRow title="API key" description="Never shown here, and never returned by the API.">
          <Text as="span" tone={settings.api_key_present ? "primary" : "tertiary"}>
            {settings.api_key_present ? "Configured" : settings.is_local ? "Not needed" : "Not set"}
          </Text>
        </SettingsRow>

        <SettingsRow
          title="Sending data externally"
          description="Hosted models receive a summary of your spending. Local models never send anything off the machine."
        >
          <Text as="span">
            {settings.is_local
              ? "Not applicable — runs locally"
              : settings.share_financial_context
                ? "Allowed"
                : "Not allowed"}
          </Text>
        </SettingsRow>

        <Text tone="tertiary" size="xs">
          These are the deployment's defaults. This workspace can point itself somewhere else
          below — an owner's decision, because it settles where everyone's data goes.
        </Text>
      </SettingsSection>

      <WorkspaceModelSection />

      <SettingsSection
        title="What the AI is used for"
        description="Each capability can use a model or the built-in engine, independently."
      >
        <SettingsRow
          title="Finding insights"
          description="Deciding what's worth telling you about. The built-in engine always runs; a model can add to it."
        >
          <Badge tone={usingLLMInsights ? "success" : "neutral"}>
            {usingLLMInsights ? "Model + built-in" : "Built-in only"}
          </Badge>
        </SettingsRow>

        <SettingsRow
          title="Writing your briefing"
          description="Turning those findings into prose. Safer to enable first — it rewords figures rather than deciding what's true."
        >
          <Badge tone={usingLLMNarration ? "success" : "neutral"}>
            {usingLLMNarration ? "Model" : "Built-in only"}
          </Badge>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection
        title="Supported providers"
        description="Set LLM_PROVIDER to one of these. Free-tier and local options mean this never has to cost anything."
      >
        <ul className="lf-llm-presets">
          {settings.presets.map((preset) => (
            <li key={preset.id} data-current={preset.id === settings.provider || undefined}>
              <div className="lf-llm-preset-main">
                <code className="lf-llm-preset-id">{preset.id}</code>
                <span className="lf-llm-preset-label">{preset.label}</span>
                {preset.free_tier && <Badge tone="success">Free tier</Badge>}
                {preset.is_local && <Badge tone="neutral">Local</Badge>}
                {!preset.requires_key && !preset.is_local && <Badge tone="neutral">No key</Badge>}
              </div>
              <div className="lf-llm-preset-meta">
                {preset.default_model && (
                  <Text as="span" tone="tertiary" size="xs">
                    default: {preset.default_model}
                  </Text>
                )}
                {preset.docs_url && (
                  <a
                    className="lf-link"
                    href={preset.docs_url}
                    target="_blank"
                    rel="noreferrer noopener"
                  >
                    Docs
                    <ExternalLink size={12} strokeWidth={2} aria-hidden="true" />
                  </a>
                )}
              </div>
            </li>
          ))}
        </ul>

        <Text tone="tertiary" size="xs">
          <Sparkles size={12} strokeWidth={2} aria-hidden="true" /> Any OpenAI-compatible endpoint
          works — use <code>custom</code> with <code>LLM_BASE_URL</code>.
        </Text>
      </SettingsSection>
    </>
  );
}

/**
 * The workspace's own model, editable by its owner.
 *
 * Blank means inherit — the deployment's provider and key apply. Filling this
 * in points *this household* somewhere else: a model on their own hardware, or
 * their own account with a vendor whose quota they would rather spend.
 *
 * Owner-only, matching the server. The reasoning is the same one recorded on
 * `Tenant.ai_enabled`: choosing the destination for a household's finances is
 * decided for everyone in the household, so it is not each member's to change.
 */
function WorkspaceModelSection() {
  const { activeWorkspace } = useAuth();
  const { data: settings } = useLLMSettings();
  const tenantId = activeWorkspace?.tenant.id;
  const isOwner = activeWorkspace?.role === "owner";

  const [current, setCurrent] = useState<WorkspaceAISettings | null>(null);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!tenantId || !isOwner) return;
    let cancelled = false;
    tenancyApi
      .getAISettings(tenantId)
      .then((data) => {
        if (cancelled) return;
        setCurrent(data);
        setProvider(data.provider);
        setModel(data.model);
        setBaseUrl(data.base_url);
      })
      .catch(() => {
        /* Inheriting is the default; a failed read must not block the page. */
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, isOwner]);

  if (!isOwner || !tenantId) return null;

  const save = async (next?: { clear: boolean }) => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const payload = next?.clear
        ? { provider: "", model: "", base_url: "", api_key: "" }
        : {
            provider,
            model,
            base_url: baseUrl,
            // Absent leaves the stored key alone; only a typed value replaces it.
            ...(apiKey ? { api_key: apiKey } : {}),
          };
      const data = await tenancyApi.setAISettings(tenantId, payload);
      setCurrent(data);
      setProvider(data.provider);
      setModel(data.model);
      setBaseUrl(data.base_url);
      setApiKey("");
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Couldn't save that — try again.");
    } finally {
      setSaving(false);
    }
  };

  const inheriting = !current?.provider;

  return (
    <SettingsSection
      title="This workspace's model"
      description="Optional. Leave it empty to use whatever the deployment provides. Set it to send this workspace's requests to a different provider — including one running on your own machine, which never sends anything outside it."
    >
      <SettingsRow
        title="Currently"
        description="Which configuration this workspace's AI requests actually use."
      >
        <Badge tone={inheriting ? "neutral" : "success"}>
          {inheriting ? "Using the deployment's" : `Own — ${current?.provider}`}
        </Badge>
      </SettingsRow>

      <SettingsRow title="Provider" description="Leave blank to inherit.">
        <Select
          label="Provider"
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
          options={[
            { value: "", label: "Use the deployment's" },
            ...(settings?.presets ?? []).map((p) => ({ value: p.id, label: p.label })),
          ]}
        />
      </SettingsRow>

      <SettingsRow title="Model" description="Blank uses the provider's default.">
        <Input
          label="Model"
          value={model}
          placeholder="e.g. llama3.2"
          onChange={(e) => setModel(e.target.value)}
        />
      </SettingsRow>

      <SettingsRow
        title="Base URL"
        description="Only for a self-hosted or unlisted endpoint. Blank uses the provider's own."
      >
        <Input
          label="Base URL"
          value={baseUrl}
          placeholder="http://localhost:11434/v1"
          onChange={(e) => setBaseUrl(e.target.value)}
        />
      </SettingsRow>

      <SettingsRow
        title="API key"
        description={
          current?.api_key_set
            ? "A key is stored. Type a new one to replace it — it is never shown again."
            : "Not needed for a local model."
        }
      >
        <Input
          label="API key"
          type="password"
          value={apiKey}
          placeholder={current?.api_key_set ? "Stored — type to replace" : ""}
          onChange={(e) => setApiKey(e.target.value)}
        />
      </SettingsRow>

      {error && <Banner tone="danger">{error}</Banner>}
      {saved && !error && <Banner tone="success">Saved. New requests use it immediately.</Banner>}

      <div style={{ display: "flex", gap: "var(--lf-space-2)" }}>
        <Button variant="primary" loading={saving} onClick={() => save()}>
          Save
        </Button>
        {!inheriting && (
          <Button variant="ghost" disabled={saving} onClick={() => save({ clear: true })}>
            Use the deployment's
          </Button>
        )}
      </div>
    </SettingsSection>
  );
}
