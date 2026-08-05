import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { investmentsApi } from "../api/investments";
import { useAuth } from "../lib/AuthContext";

/** Every query in this module shares a prefix so a trade can invalidate the
 * whole portfolio view in one call — holdings, summary and history all move
 * together after a buy or sell. */
const PREFIX = "investments";

export function useHoldings() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "holdings", activeWorkspace?.tenant.id],
    queryFn: () => investmentsApi.holdings(),
    enabled: !!activeWorkspace,
  });
}

export function usePortfolio() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "portfolio", activeWorkspace?.tenant.id],
    queryFn: () => investmentsApi.portfolio(),
    enabled: !!activeWorkspace,
  });
}

export function usePortfolioHistory(months = 12) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "history", activeWorkspace?.tenant.id, months],
    queryFn: () => investmentsApi.history(months),
    enabled: !!activeWorkspace,
  });
}

export function useSecurities() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [PREFIX, "securities", activeWorkspace?.tenant.id],
    queryFn: () => investmentsApi.securities(),
    enabled: !!activeWorkspace,
  });
}

export function useCreateSecurity() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: investmentsApi.createSecurity,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [PREFIX] }),
  });
}

export function useTrade() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      action,
      payload,
    }: {
      action: "buy" | "sell";
      payload: Parameters<typeof investmentsApi.trade>[1];
    }) => investmentsApi.trade(action, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PREFIX] });
      // A trade moves cash, so account balances and net worth move too.
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["net-worth"] });
    },
  });
}

export function useRecordPrice() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: investmentsApi.recordPrice,
    // A price change moves market value but not the ledger, so only the
    // portfolio views need refreshing.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [PREFIX] }),
  });
}

export function useRecordDividend() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: investmentsApi.recordDividend,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PREFIX] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
    },
  });
}

export function useRecordInterest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: investmentsApi.recordInterest,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [PREFIX] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
    },
  });
}
