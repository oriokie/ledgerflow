import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

// The currency step is answered in place, so the checklist reaches into auth
// context for the workspace it would be saving against.
vi.mock("../../lib/AuthContext", () => ({
  useAuth: () => ({
    activeWorkspace: {
      role: "owner",
      tenant: { id: "t1", base_currency: "USD", base_currency_chosen_at: null },
    },
  }),
}));

import { GettingStarted } from "./GettingStarted";
import { buildSteps, type OnboardingState } from "./onboarding";

const EMPTY: OnboardingState = {
  hasCurrency: false,
  hasAccount: false,
  hasTransaction: false,
  hasBudget: false,
  hasGoal: false,
  hasTeammate: false,
};

/** Everything before `id` done — for driving the checklist to a given step. */
function upTo(id: string): Partial<OnboardingState> {
  const order: [string, keyof OnboardingState][] = [
    ["currency", "hasCurrency"],
    ["account", "hasAccount"],
    ["transaction", "hasTransaction"],
    ["budget", "hasBudget"],
    ["goal", "hasGoal"],
    ["invite", "hasTeammate"],
  ];
  const state: Partial<OnboardingState> = {};
  for (const [stepId, flag] of order) {
    if (stepId === id) break;
    state[flag] = true;
  }
  return state;
}

function renderStarted(state: Partial<OnboardingState>, onDismiss?: () => void) {
  return render(
    <MemoryRouter>
      <GettingStarted state={{ ...EMPTY, ...state }} onDismiss={onDismiss} />
    </MemoryRouter>,
  );
}

describe("buildSteps", () => {
  it("covers the setup milestones in order, currency first", () => {
    // Currency leads because every later step creates something denominated in
    // it, and changing it afterwards is the expensive correction.
    expect(buildSteps(EMPTY).map((s) => s.id)).toEqual([
      "currency",
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

  it("deep-links every navigating action straight into its create surface", () => {
    // Landing on a page and leaving the user to hunt for the button is the
    // friction this is meant to remove.
    for (const step of buildSteps(EMPTY)) {
      if (step.id === "invite") continue; // members has its own invite flow
      if (step.inline) continue; // answered in the checklist, nowhere to go
      expect(step.cta?.to).toMatch(/[?&](add|import)=1/);
    }
  });

  it("answers the currency step in place rather than sending the user away", () => {
    const currency = buildSteps(EMPTY).find((s) => s.id === "currency")!;
    expect(currency.inline).toBe("currency");
    expect(currency.cta).toBeUndefined();
  });
});

describe("GettingStarted", () => {
  it("asks a brand-new user for their currency first, in place", () => {
    renderStarted({});
    expect(screen.getByText("Choose your currency")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /use this currency/i })).toBeInTheDocument();
    // Only the current step exposes an action, so there's one obvious next move.
    expect(screen.queryByRole("link", { name: /add account/i })).not.toBeInTheDocument();
  });

  it("guides on to adding an account once the currency is chosen", () => {
    renderStarted(upTo("account"));
    expect(screen.getByText("Add your first account")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /add account/i })).toHaveAttribute("href", "/accounts?add=1");
    expect(screen.queryByRole("link", { name: /add transaction/i })).not.toBeInTheDocument();
  });

  it("advances to the transaction step once an account exists", () => {
    renderStarted(upTo("transaction"));
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

  it("keeps guiding past the first steps instead of disappearing", () => {
    renderStarted(upTo("budget"));
    expect(screen.getByRole("link", { name: /create budget/i })).toHaveAttribute("href", "/budgets?add=1");
  });

  it("reports progress in words as well as a bar", () => {
    renderStarted(upTo("budget"));
    expect(screen.getByText("3 of 6 done")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: /setup progress/i });
    expect(bar).toHaveAttribute("aria-valuenow", "3");
    expect(bar).toHaveAttribute("aria-valuemax", "6");
  });

  it("acknowledges completion rather than showing a dead checklist", () => {
    renderStarted({
      hasCurrency: true,
      hasAccount: true,
      hasTransaction: true,
      hasBudget: true,
      hasGoal: true,
      hasTeammate: true,
    });
    expect(screen.getByText(/you're all set/i)).toBeInTheDocument();
    expect(screen.getByText("6 of 6 done")).toBeInTheDocument();
  });

  it("can be dismissed, because guidance you can't remove is nagging", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    renderStarted({}, onDismiss);
    await user.click(screen.getByRole("button", { name: /dismiss the setup checklist/i }));
    expect(onDismiss).toHaveBeenCalled();
  });
});
