import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Insight } from "../../api/types";
import { InsightCard } from "./InsightCard";

const INSIGHT: Insight = {
  id: "i1",
  kind: "overspending",
  severity: "warning",
  status: "new",
  title: "Over budget on Groceries",
  body: "You've spent USD 412 against a USD 350 limit — USD 62 over.",
  rationale:
    "Your Groceries budget line is set to USD 350 for this period, and transactions categorised to it total USD 412.",
  evidence: { limit_minor: 35_000, spent_minor: 41_200, over_minor: 6_200 },
  action: { action: "review_category", category_id: "c1" },
  priority_score: 58,
  period_start: null,
  period_end: null,
  expires_on: "2026-06-30",
  provider: "RuleBasedCoach",
  provider_kind: "rule",
  provider_version: "1.0",
  related_transaction_id: null,
  related_category_id: "c1",
  related_account_id: null,
  created_at: "2026-06-15T09:00:00Z",
};

function renderCard(overrides: Partial<Insight> = {}, handlers = {}) {
  return render(
    <MemoryRouter>
      <InsightCard insight={{ ...INSIGHT, ...overrides }} currency="USD" {...handlers} />
    </MemoryRouter>,
  );
}

describe("InsightCard", () => {
  it("shows the title and body without needing to be expanded", () => {
    renderCard();
    expect(screen.getByRole("heading", { name: /over budget on groceries/i })).toBeInTheDocument();
    expect(screen.getByText(/412/)).toBeInTheDocument();
  });

  it("keeps the rationale behind a disclosure rather than a tooltip", async () => {
    const user = userEvent.setup();
    renderCard();

    // "Why" is a real, focusable control — a user who can check one claim will
    // believe the next.
    const toggle = screen.getByRole("button", { name: /why am i seeing this/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(INSIGHT.rationale)).not.toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(INSIGHT.rationale)).toBeInTheDocument();
  });

  it("shows the figures the claim was computed from", async () => {
    const user = userEvent.setup();
    renderCard();
    await user.click(screen.getByRole("button", { name: /why am i seeing this/i }));

    expect(screen.getByText("Budget limit")).toBeInTheDocument();
    expect(screen.getByText("Over by")).toBeInTheDocument();
    expect(screen.getByText("$350.00")).toBeInTheDocument();
  });

  it("names the provider that produced the insight", async () => {
    const user = userEvent.setup();
    renderCard();
    await user.click(screen.getByRole("button", { name: /why am i seeing this/i }));
    // Matters more once an LLM can author these.
    expect(screen.getByText(/RuleBasedCoach \(rule v1\.0\)/)).toBeInTheDocument();
  });

  it("ignores evidence keys it has no label for", async () => {
    const user = userEvent.setup();
    renderCard({ evidence: { over_minor: 6_200, some_internal_key: 99 } });
    await user.click(screen.getByRole("button", { name: /why am i seeing this/i }));

    // Dumping an opaque dict would defeat the point of evidence.
    expect(screen.getByText("Over by")).toBeInTheDocument();
    expect(screen.queryByText("some_internal_key")).not.toBeInTheDocument();
  });

  it("links the primary action to a real destination", () => {
    renderCard();
    expect(screen.getByRole("link", { name: /see transactions/i })).toHaveAttribute(
      "href",
      "/transactions?category_id=c1",
    );
  });

  it("omits the action button for an unrecognised verb", () => {
    // A link that goes nowhere is worse than no link.
    renderCard({ action: { action: "teleport" } });
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("emits the insight id on dismiss and bookmark", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    const onBookmark = vi.fn();
    renderCard({}, { onDismiss, onBookmark });

    await user.click(screen.getByRole("button", { name: /dismiss this insight/i }));
    expect(onDismiss).toHaveBeenCalledWith("i1");

    await user.click(screen.getByRole("button", { name: /bookmark this insight/i }));
    expect(onBookmark).toHaveBeenCalledWith("i1");
  });

  it("reflects a bookmarked state on the control", () => {
    renderCard({ status: "bookmarked" }, { onBookmark: vi.fn() });
    expect(screen.getByRole("button", { name: /bookmarked/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("hides the action controls when no handlers are supplied", () => {
    // Dismissed insights render read-only; offering "dismiss" again is a dead
    // control.
    renderCard();
    expect(screen.queryByRole("button", { name: /dismiss/i })).not.toBeInTheDocument();
  });

  it("marks severity for styling and for assistive tech", () => {
    const { container } = renderCard({ severity: "critical" });
    expect(container.querySelector('[data-severity="critical"]')).toBeInTheDocument();
    // The label is text, not colour alone.
    const card = container.querySelector(".lf-insight")!;
    expect(within(card as HTMLElement).getByText("Needs attention")).toBeInTheDocument();
  });
});
