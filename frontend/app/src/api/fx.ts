import { api } from "./client";
import type { CurrencyMeta } from "../lib/currencies";

const GLOBAL = { skipTenant: true } as const;

export const fxApi = {
  currencies: () => api.get<CurrencyMeta[]>("/fx/currencies/", GLOBAL),
  rates: (base = "USD") =>
    api.get<{ base: string; rates: Record<string, number> }>(`/fx/rates/?base=${base}`, GLOBAL),
  convert: (amountMinor: number, from: string, to: string) =>
    api.get<{ amount_minor: number; from: string; to: string; converted_minor: number | null }>(
      `/fx/convert/?amount_minor=${amountMinor}&from=${from}&to=${to}`,
      GLOBAL,
    ),
};
