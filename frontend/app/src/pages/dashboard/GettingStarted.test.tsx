import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { GettingStarted } from "./GettingStarted";
import { buildSteps, type OnboardingState } from "./onboarding";

const EMPTY: OnboardingState = {
  hasAccount: false,
  hasTransaction: false,
  hasBudget: false,
  hasGoal: false,
  hasTeammate: false,
};

function renderStarted(state: Partial<OnboardingState>, onDismiss?: () => void) {
  return render(
    <MemoryRouter>
      <GettingStarted state={{ ...EMPTY, ...state }} onDismiss={onDismiss} />
    </MemoryRouter>,
  );
}

describe("buildSteps", () => {
  it("covers the five setup milestones in order", () => {
    expect(buildSteps(EMPTY).map((s) => s.id)).toEqual([
      "account",
      "transaction",
      "budget",
      "goal",
      "invite",
    ]);
  });

  it("marks a step done from the matching state flag", () => {
    const steps = buildSteps({ ...EMPTY, hasAccount: true, hasGoal: true });
    expect(steps.find((s) => s.id === "account")!.done).toBe(true);
    expect(steps.find((s) => s.id === "goal")!.done).toBe(true);
    expect(steps.find((s) => s.id === "budget")!.done).toBe(false);
  });

  it("deep-links every action straight into its create surface", () => {
    // Landing on a page and leaving the user to hunt for the button is the
    // friction this is meant to remove.
    for (const step of buildSteps(EMPTY)) {
      if (step.id === "invite") continue; // members has its own invite flow
      expect(step.cta?.to).toMatch(/[?&](add|import)=1/);
    }
  });
});

describe("GettingStarted", () => {
  it("guides a brand-new user to add an account first", () => {
    renderStarted({});
    expect(screen.getByText("Add your first account")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /add account/i })).toHaveAttribute("href", "/accounts?add=1");
    // Only the current step exposes an action, so there's one obvious next move.
    expect(screen.queryByRole("link", { name: /add transaction/i })).not.toBeInTheDocument();
  });

  it("advances to the transaction step once an account exists", () => {
    renderStarted({ hasAccount: true });
    expect(screen.getByRole("link", { name: /add transaction/i })).toHaveAttribute(
      "href",
      "/transactions?add=1",
    );
    expect(screen.getByRole("link", { name: /import from your bank/i })).toHaveAttribute(
      "href",
      "/transactions?import=1",
    );
    expect(screen.queryByRole("link", { name: /add account/i })).not.toBeInTheDocument();
  });

  it("keeps guiding past the first two steps instead of disappearing", () => {
    renderStarted({ hasAccount: true, hasTransaction: true });
    expect(screen.getByRole("link", { name: /create budget/i })).toHaveAttribute("href", "/budgets?add=1");
  });

  it("reports progress in words as well as a bar", () => {
    renderStarted({ hasAccount: true, hasTransaction: true });
    expect(screen.getByText("2 of 5 done")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: /setup progress/i });
    expect(bar).toHaveAttribute("aria-valuenow", "2");
    expect(bar).toHaveAttribute("aria-valuemax", "5");
  });

  it("acknowledges completion rather than showing a dead checklist", () => {
    renderStarted({
      hasAccount: true,
      hasTransaction: true,
      hasBudget: true,
      hasGoal: true,
      hasTeammate: true,
    });
    expect(screen.getByText(/you're all set/i)).toBeInTheDocument();
    expect(screen.getByText("5 of 5 done")).toBeInTheDocument();
  });

  it("can be dismissed, because guidance you can't remove is nagging", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    renderStarted({}, onDismiss);
    await user.click(screen.getByRole("button", { name: /dismiss the setup checklist/i }));
    expect(onDismiss).toHaveBeenCalled();
  });
});
