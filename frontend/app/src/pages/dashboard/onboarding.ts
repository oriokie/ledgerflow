/**
 * Onboarding checklist model.
 *
 * Kept apart from the component so the ordering, completion rules and deep
 * links can be tested without rendering — and so the view file exports only a
 * component (which is what React Fast Refresh needs to work reliably).
 */

export interface OnboardingState {
  hasAccount: boolean;
  hasTransaction: boolean;
  hasBudget: boolean;
  hasGoal: boolean;
  hasTeammate: boolean;
}

export interface OnboardingStep {
  id: string;
  title: string;
  body: string;
  done: boolean;
  cta?: { label: string; to: string };
  secondary?: { label: string; to: string };
}

/**
 * The five setup milestones, in the order a person actually needs them.
 *
 * Every action deep-links into its create surface (`?add=1`) rather than the
 * destination page: dropping someone on Budgets and leaving them to find the
 * button is the friction this checklist exists to remove.
 */
export function buildSteps(state: OnboardingState): OnboardingStep[] {
  return [
    {
      id: "account",
      title: "Add your first account",
      body: "A checking account, savings, or a card — whatever you'd like to track.",
      done: state.hasAccount,
      cta: { label: "Add account", to: "/accounts?add=1" },
    },
    {
      id: "transaction",
      title: "Record some activity",
      body: "Add a transaction by hand, or import a CSV to backfill months at once.",
      done: state.hasTransaction,
      cta: { label: "Add transaction", to: "/transactions?add=1" },
      secondary: { label: "or import from your bank", to: "/transactions?import=1" },
    },
    {
      id: "budget",
      title: "Set a budget",
      body: "Pick limits for the categories you actually want to watch. You can change them any time.",
      done: state.hasBudget,
      cta: { label: "Create budget", to: "/budgets?add=1" },
    },
    {
      id: "goal",
      title: "Name something you're saving for",
      body: "A trip, a deposit, an emergency fund — progress is far easier to keep up when it has a name.",
      done: state.hasGoal,
      cta: { label: "Create goal", to: "/goals?add=1" },
    },
    {
      id: "invite",
      title: "Invite the people you share money with",
      body: "Partners and family see the same accounts and budgets, with roles you control.",
      done: state.hasTeammate,
      cta: { label: "Invite someone", to: "/members" },
    },
  ];
}
