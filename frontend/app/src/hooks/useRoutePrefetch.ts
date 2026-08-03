import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef } from "react";
import { financeApi } from "../api/finance";
import { useAuth } from "../lib/AuthContext";

/**
 * What each route needs in cache before it can paint something real.
 *
 * Deliberately shallow: one or two cheap, highly cacheable lists per route.
 * Prefetching a route's *entire* dependency graph on hover would turn an idle
 * mouse crossing the sidebar into a burst of requests — the opposite of fast.
 */
const ROUTE_PREFETCH: Record<string, ("accounts" | "categories" | "transactions" | "bills")[]> = {
  "/": ["accounts", "categories"],
  "/transactions": ["transactions", "accounts", "categories"],
  "/accounts": ["accounts"],
  "/categories": ["categories"],
  "/bills": ["bills", "accounts"],
  "/budgets": ["categories"],
  "/analytics": ["categories"],
};

/**
 * Prefetches a route's data on navigation *intent* — pointer-enter or focus of
 * a nav link — so the page is usually already populated by the time the click
 * lands. This is the cheapest perceived-performance win available: the user's
 * own hover latency (100–300ms) is dead time we can spend on the network.
 *
 * Guards that keep it honest:
 *   • Each route is prefetched at most once per session (`primed`), so sweeping
 *     the cursor down the sidebar can't fan out into repeated requests.
 *   • `prefetchQuery` respects `staleTime`, so anything already fresh is a
 *     no-op rather than a duplicate fetch.
 *   • Failures are swallowed. A speculative fetch must never surface an error
 *     for a page the user never actually visited.
 */
export function useRoutePrefetch() {
  const queryClient = useQueryClient();
  const { activeWorkspace } = useAuth();
  const tenantId = activeWorkspace?.tenant.id;
  const primed = useRef(new Set<string>());

  return useCallback(
    (path: string) => {
      if (!tenantId) return;
      const needs = ROUTE_PREFETCH[path];
      if (!needs || primed.current.has(path)) return;
      primed.current.add(path);

      for (const need of needs) {
        switch (need) {
          case "accounts":
            void queryClient
              .prefetchQuery({
                queryKey: ["accounts", tenantId],
                queryFn: () => financeApi.listAccounts(),
                staleTime: 30_000,
              })
              .catch(() => {});
            break;
          case "categories":
            void queryClient
              .prefetchQuery({
                queryKey: ["categories", tenantId],
                queryFn: () => financeApi.listCategories(),
                staleTime: 5 * 60_000,
              })
              .catch(() => {});
            break;
          case "transactions":
            void queryClient
              .prefetchQuery({
                queryKey: ["transactions", tenantId, {}],
                queryFn: () => financeApi.listTransactions({}),
                staleTime: 30_000,
              })
              .catch(() => {});
            break;
          case "bills":
            void queryClient
              .prefetchQuery({
                queryKey: ["bills", tenantId, {}],
                queryFn: () => financeApi.listBills({}),
                staleTime: 30_000,
              })
              .catch(() => {});
            break;
        }
      }
    },
    [queryClient, tenantId],
  );
}

/** Exposed for tests and for keeping the nav config honest about coverage. */
export const PREFETCHABLE_ROUTES = Object.keys(ROUTE_PREFETCH);
