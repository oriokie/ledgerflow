import { useQuery } from "@tanstack/react-query";
import { ledgerApi } from "../api/ledger";
import { useAuth } from "../lib/AuthContext";

export function useLedgerAccounts(enabled: boolean) {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: ["ledger-accounts", activeWorkspace?.tenant.id],
    queryFn: () => ledgerApi.listAccounts(),
    enabled: !!activeWorkspace && enabled,
  });
}
