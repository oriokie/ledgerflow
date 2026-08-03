import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Briefing } from "../../api/types";
import { BriefingCard } from "./BriefingCard";
import { providerLabel } from "./providerLabel";

const BRIEFING: Briefing = {
  id: "b1",
  period: "daily",
  period_start: "2026-06-15",
  period_end: "2026-06-15",
  headline: "Balance projected to go negative on 20 Jun",
  summary: "1 thing needs attention now: Balance projected to go negative on 20 Jun.",
  metrics: {
    currency: "USD",
    savings_rate: 0.18,
    insight_count: 4,
    critical_count: 1,
    warning_count: 2,
    opportunity_count: 1,
  },
  provider: "TemplateNarrator",
  insights: [],
};

function renderCard(overrides: Partial<Briefing> | null = {}, props = {}) {
  return render(
    <BriefingCard
      briefing={overrides === null ? undefined : { ...BRIEFING, ...overrides }}
      period="daily"
      onPeriodChange={vi.fn()}
      {...props}
    />,
  );
}

describe("BriefingCard", () => {
  it("leads with the headline and summary", () => {
    renderCard();
    expect(screen.getByRole("heading", { name: /go negative on 20 jun/i })).toBeInTheDocument();
    expect(screen.getByText(/1 thing needs attention now/i)).toBeInTheDocument();
  });

  it("shows the counts the narrator wrote from", () => {
    // Prose is easy to skim past; the figures give something to anchor on.
    renderCard();
    expect(screen.getByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText("Worth a look")).toBeInTheDocument();
    expect(screen.getByText("18%")).toBeInTheDocument();
  });

  it("omits count rows that are zero", () => {
    renderCard({ metrics: { ...BRIEFING.metrics, critical_count: 0, warning_count: 0 } });
    expect(screen.queryByText("Needs attention")).not.toBeInTheDocument();
    expect(screen.getByText("Opportunities")).toBeInTheDocument();
  });

  it("says how the briefing was written without leaking the class name", () => {
    renderCard();
    expect(screen.getByText(/Written from your own figures/)).toBeInTheDocument();
    // The provider is an internal identifier. Printing it verbatim ended the
    // trust sentence in "…by TemplateNarrator."
    expect(screen.queryByText(/TemplateNarrator/)).not.toBeInTheDocument();
  });

  it("distinguishes an AI-written briefing from a rule-written one", () => {
    expect(providerLabel("apps.intelligence.providers.coach.TemplateNarrator")).toMatch(/No AI involved/);
    expect(providerLabel("AnthropicNarrator")).toMatch(/Written by AI/);
    expect(providerLabel(undefined)).toMatch(/Written from your own figures/);
  });

  it("switches period through the segmented control", async () => {
    const user = userEvent.setup();
    const onPeriodChange = vi.fn();
    renderCard({}, { onPeriodChange });

    await user.click(screen.getByRole("radio", { name: "This week" }));
    expect(onPeriodChange).toHaveBeenCalledWith("weekly");
  });

  it("explains the absence rather than rendering blank", () => {
    renderCard(null);
    expect(screen.getByText(/no briefing yet/i)).toBeInTheDocument();
  });
});
