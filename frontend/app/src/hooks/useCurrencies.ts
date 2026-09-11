import { useQuery } from "@tanstack/react-query";

import { fxApi } from "../api/fx";
import { CURRENCIES, currencyOptions, hydrateCurrencyCatalog } from "../lib/currencies";

/** Active catalog from the server, falling back to the seeded list while it loads. */
export function useCurrencyOptions() {
  const { data } = useQuery({
    queryKey: ["fx", "currencies"],
    queryFn: fxApi.currencies,
    staleTime: 5 * 60_000,
    placeholderData: [...CURRENCIES],
  });
  const list = data && data.length > 0 ? data : CURRENCIES;
  hydrateCurrencyCatalog(list);
  return currencyOptions(list);
}
