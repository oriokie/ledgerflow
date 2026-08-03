import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { debtApi } from "../api/debt";
import type { PayoffStrategy } from "../api/types";
import { useAuth } from "../lib/AuthContext";

const PREFIX = "debt";

/** Liability accounts that exist, including ones with nothing owed.
 *
 * The debt page needs this to tell "you have no cards" apart from "you added a
 * card and haven't used it yet" — without it, following the empty state's own
 * advice appears to do nothing.
 */
export function useTrackedLiabilities() {
  return useQuery({ queryKey: ["debt", "tracked"], queryFn: debtApi.tracked });
}

export function useDebts() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "list", activeWorkspace?.tenant.id],
    queryFn: () => debtApi.debts(),
    enabled: !!activeWorkspace,
  });
}

export function useDebtSummary(extraMonthlyMinor = 0) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "summary", activeWorkspace?.tenant.id, extraMonthlyMinor],
    queryFn: () => debtApi.summary(extraMonthlyMinor),
    enabled: !!activeWorkspace,
  });
}

/**
 * A payoff simulation.
 *
 * `keepPreviousData` matters here: the extra-payment slider re-queries on every
 * change, and without it the whole plan would blank out mid-drag. Holding the
 * last result while the next loads makes the simulation feel live.
 */
export function usePayoffPlan(params: {
  strategy?: PayoffStrategy;
  extra_monthly_minor?: number;
  months?: number;
}) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "payoff", activeWorkspace?.tenant.id, params],
    queryFn: () => debtApi.payoff(params),
    enabled: !!activeWorkspace,
    placeholderData: (previous) => previous,
  });
}

export function useSetDebtTerms() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      payload,
    }: {
      accountId: string;
      payload: Parameters<typeof debtApi.setTerms>[1];
    }) => debtApi.setTerms(accountId, payload),
    // Terms change every derived figure — balances don't move, but the plan,
    // the alerts and the recommendation all do.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [PREFIX] }),
  });
}

/** The Debt Stress Score. Always arrives with its derivation attached. */
export function useDebtStress() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "stress", activeWorkspace?.tenant.id],
    queryFn: () => debtApi.stress(),
    enabled: !!activeWorkspace,
  });
}

export function useBorrowingCost() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "cost", activeWorkspace?.tenant.id],
    queryFn: () => debtApi.borrowingCost(),
    enabled: !!activeWorkspace,
  });
}

/**
 * Scenario comparison.
 *
 * A mutation rather than a query because the scenarios are the input, and they
 * change as the user edits them — modelling that as a query key would cache a
 * result per keystroke.
 */
export function useCompareScenarios() {
  return useMutation({
    mutationFn: (scenarios: Parameters<typeof debtApi.compareScenarios>[0]) =>
      debtApi.compareScenarios(scenarios),
  });
}

export function useSimulateRefinance() {
  return useMutation({
    mutationFn: ({
      accountId,
      payload,
    }: {
      accountId: string;
      payload: Parameters<typeof debtApi.simulateRefinance>[1];
    }) => debtApi.simulateRefinance(accountId, payload),
  });
}


export function useDebtAnalytics(params: {
  strategy?: PayoffStrategy;
  extra_monthly_minor?: number;
  months?: number;
}) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "analytics", activeWorkspace?.tenant.id, params],
    queryFn: () => debtApi.analytics(params),
    enabled: !!activeWorkspace,
    placeholderData: (previous) => previous,
  });
}
