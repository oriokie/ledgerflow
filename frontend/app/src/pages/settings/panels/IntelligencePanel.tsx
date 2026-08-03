import { AlertCircle, CheckCircle2, ExternalLink, HardDrive, Sparkles } from "lucide-react";
import { useState } from "react";
import { useLLMSettings, useSetTenantAiEnabled } from "../../../hooks/useCoach";
import { useAuth } from "../../../lib/AuthContext";
import { Badge, Banner, Skeleton, Switch, Text } from "../../../ui";
import { SettingsRow, SettingsSection } from "../components";

/**
 * AI configuration — read-only by design.
 *
 * LLM setup lives in environment variables, not in the database, and this panel
 * reports it rather than editing it. That's deliberate: a workspace member
 * changing the model endpoint would be deciding, on everyone else's behalf,
 * where the household's financial data gets sent. That belongs to whoever
 * deploys the instance.
 *
 * The panel's real job is to answer "I turned it on, why is nothing
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
          Provider, model and API key are set once for the whole deployment, not per workspace —
          a member picking where the household's data gets sent would be deciding that for
          everyone else on this account.
        </Text>
      </SettingsSection>

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
