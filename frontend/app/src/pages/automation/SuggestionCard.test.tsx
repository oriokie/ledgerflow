import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AutomationSuggestion } from "../../api/types";
import { SuggestionCard } from "./SuggestionCard";

const SUGGESTION: AutomationSuggestion = {
  id: "s1",
  kind: "duplicate",
  status: "pending",
  confidence: 0.6,
  reason: "Same amount and merchant on the same day. Worth checking — repeats are often legitimate.",
  payload: { amount_minor: 1_250 },
  merchant_key: "cornershop",
  primary_transaction_id: "t1",
  transaction_ids: ["t1", "t2"],
  created_at: "2026-07-01T09:00:00Z",
  decided_at: null,
};

const onSelect = vi.fn();
const onDecide = vi.fn();

function renderCard(overrides: Partial<AutomationSuggestion> = {}, selected = false) {
  return render(
    <SuggestionCard
      suggestion={{ ...SUGGESTION, ...overrides }}
      selected={selected}
      onSelect={onSelect}
      onDecide={onDecide}
    />,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("SuggestionCard", () => {
  it("shows the reasoning without needing to be expanded", () => {
    // This asks the user to act, so the reasoning can't sit behind a
    // disclosure the way a coach insight's can.
    renderCard();
    expect(screen.getByText(/same amount and merchant/i)).toBeInTheDocument();
  });

  it("bands confidence rather than printing a false-precision percentage", () => {
    renderCard({ confidence: 0.6 });
    expect(screen.getByText("Worth checking")).toBeInTheDocument();
    expect(screen.queryByText(/60%/)).not.toBeInTheDocument();
  });

  it("moves through the confidence bands", () => {
    const { unmount } = renderCard({ confidence: 0.95 });
    expect(screen.getByText("Very likely")).toBeInTheDocument();
    unmount();
    renderCard({ confidence: 0.7 });
    expect(screen.getByText("Likely")).toBeInTheDocument();
  });

  it("says how many transactions are involved when it's more than one", () => {
    renderCard();
    expect(screen.getByText("2 transactions")).toBeInTheDocument();
  });

  it("omits the count for a single-transaction suggestion", () => {
    renderCard({ kind: "category", transaction_ids: ["t1"] });
    expect(screen.queryByText(/transactions$/)).not.toBeInTheDocument();
  });

  it("offers both accept and dismiss, never just accept", () => {
    // Automation proposes; a person disposes. A card with only an accept
    // button isn't a review.
    renderCard();
    expect(screen.getByRole("button", { name: /accept/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /dismiss/i })).toBeInTheDocument();
  });

  it("emits the decision with the suggestion id", async () => {
    const user = userEvent.setup();
    renderCard();

    await user.click(screen.getByRole("button", { name: /accept/i }));
    expect(onDecide).toHaveBeenCalledWith("s1", "approve");

    await user.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(onDecide).toHaveBeenCalledWith("s1", "reject");
  });

  it("supports selection for bulk review", async () => {
    const user = userEvent.setup();
    renderCard();
    await user.click(screen.getByRole("checkbox"));
    expect(onSelect).toHaveBeenCalledWith("s1");
  });

  it("marks the kind for styling and states it in words", () => {
    const { container } = renderCard({ kind: "transfer" });
    expect(container.querySelector('[data-kind="transfer"]')).toBeInTheDocument();
    expect(screen.getByText("Transfer")).toBeInTheDocument();
  });
});
