import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LLMSettings } from "../../../api/types";

const settings = vi.fn();
const setTenantAiMutateAsync = vi.fn();
vi.mock("../../../hooks/useCoach", () => ({
  useLLMSettings: () => settings(),
  useSetTenantAiEnabled: () => ({ mutateAsync: setTenantAiMutateAsync, isPending: false }),
}));

const authRole = vi.fn(() => "owner");
vi.mock("../../../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { role: authRole(), tenant: { id: "t1" } } }),
}));

import { IntelligencePanel } from "./IntelligencePanel";

const BASE: LLMSettings = {
  enabled: false,
  available: false,
  reason: "LLM features are turned off.",
  provider: "custom",
  provider_label: "Custom (OpenAI-compatible)",
  model: "",
  base_url: "",
  api_key_present: false,
  is_local: false,
  share_financial_context: false,
  tenant_ai_enabled: true,
  insight_provider: "apps.intelligence.providers.coach.RuleBasedCoach",
  narrative_provider: "apps.intelligence.providers.coach.TemplateNarrator",
  presets: [
    {
      id: "groq",
      label: "Groq",
      default_model: "llama-3.3-70b-versatile",
      requires_key: true,
      free_tier: true,
      is_local: false,
      docs_url: "https://console.groq.com/docs",
    },
    {
      id: "ollama",
      label: "Ollama (local)",
      default_model: "llama3.2",
      requires_key: false,
      free_tier: true,
      is_local: true,
      docs_url: "https://ollama.com",
    },
  ],
};

function renderPanel(overrides: Partial<LLMSettings> = {}, isLoading = false) {
  settings.mockReturnValue({ data: isLoading ? undefined : { ...BASE, ...overrides }, isLoading });
  return render(<IntelligencePanel />);
}

beforeEach(() => {
  vi.clearAllMocks();
  authRole.mockReturnValue("owner");
});

describe("IntelligencePanel", () => {
  it("explains why provider/model stays deployment-level, now that a real toggle sits above it", () => {
    // A user seeing one working switch might reasonably expect the rest of
    // the panel to be editable too — this is the one sentence stopping that
    // assumption from turning into a support ticket.
    renderPanel();
    expect(screen.getByText(/set once for the whole deployment, not per workspace/i)).toBeInTheDocument();
  });

  it("shows the workspace AI switch in its actual on/off state", () => {
    renderPanel({ tenant_ai_enabled: true });
    expect(screen.getByRole("switch", { name: /use ai for this workspace/i })).toBeChecked();
  });

  it("an owner can turn the workspace switch off", async () => {
    setTenantAiMutateAsync.mockResolvedValue({ tenant_ai_enabled: false });
    const user = userEvent.setup();
    renderPanel({ tenant_ai_enabled: true });

    await user.click(screen.getByRole("switch", { name: /use ai for this workspace/i }));
    await waitFor(() => expect(setTenantAiMutateAsync).toHaveBeenCalledWith(false));
  });

  it("a plain member sees the switch disabled, with an explanation", () => {
    // The API would reject this anyway (403); disabling it here means the
    // member sees why up front rather than clicking and hitting an error.
    authRole.mockReturnValue("member");
    renderPanel({ tenant_ai_enabled: true });

    expect(screen.getByRole("switch", { name: /use ai for this workspace/i })).toBeDisabled();
    expect(screen.getByText(/ask a workspace owner or admin/i)).toBeInTheDocument();
  });

  it("an admin, not just an owner, can toggle it", () => {
    authRole.mockReturnValue("admin");
    renderPanel();
    expect(screen.getByRole("switch", { name: /use ai for this workspace/i })).not.toBeDisabled();
  });

  it("shows an error without losing the panel if the toggle fails", async () => {
    setTenantAiMutateAsync.mockRejectedValue(new Error("network error"));
    const user = userEvent.setup();
    renderPanel({ tenant_ai_enabled: true });

    await user.click(screen.getByRole("switch", { name: /use ai for this workspace/i }));
    expect(await screen.findByText(/couldn't update this/i)).toBeInTheDocument();
    // The rest of the panel is still there — a failed toggle shouldn't blank
    // the whole settings page.
    expect(screen.getByText("Not active")).toBeInTheDocument();
  });
  it("states plainly when AI is not active", () => {
    renderPanel();
    expect(screen.getByText("Not active")).toBeInTheDocument();
  });

  it("explains why, which is the panel's whole job", () => {
    // "I turned it on and nothing happened" is the most common and most silent
    // failure here.
    renderPanel({ reason: "Groq needs an API key." });
    expect(screen.getByText(/groq needs an api key/i)).toBeInTheDocument();
  });

  it("shows no reason banner once it is working", () => {
    renderPanel({ enabled: true, available: true, reason: "", provider_label: "Groq" });
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.queryByText(/needs an api key/i)).not.toBeInTheDocument();
  });

  it("never renders the API key itself", () => {
    const { container } = renderPanel({ api_key_present: true });
    expect(screen.getByText("Configured")).toBeInTheDocument();
    // Presence only — the credential must not cross the API boundary at all.
    expect(container.textContent).not.toMatch(/sk-|Bearer/);
  });

  it("says a key is not needed for a local provider", () => {
    renderPanel({ is_local: true, provider: "ollama", provider_label: "Ollama (local)" });
    expect(screen.getByText("Not needed")).toBeInTheDocument();
  });

  it("marks external data sharing as not applicable for local models", () => {
    renderPanel({ is_local: true });
    expect(screen.getByText(/not applicable — runs locally/i)).toBeInTheDocument();
  });

  it("reports each capability independently", () => {
    renderPanel({ insight_provider: "apps.intelligence.providers.llm_coach.LLMCoach" });
    expect(screen.getByText("Model + built-in")).toBeInTheDocument();
    // Narration still on the built-in engine.
    expect(screen.getByText("Built-in only")).toBeInTheDocument();
  });

  it("lists providers with their free-tier and local badges", () => {
    renderPanel();
    expect(screen.getByText("groq")).toBeInTheDocument();
    expect(screen.getByText("ollama")).toBeInTheDocument();
    expect(screen.getAllByText("Free tier")).toHaveLength(2);
    expect(screen.getByText("Local")).toBeInTheDocument();
  });

  it("highlights the provider currently in use", () => {
    const { container } = renderPanel({ provider: "groq" });
    const current = container.querySelector("[data-current]");
    expect(current?.textContent).toContain("Groq");
  });

  it("renders a skeleton while loading", () => {
    const { container } = renderPanel({}, true);
    expect(container.querySelector(".lf-skeleton")).toBeInTheDocument();
  });
});
