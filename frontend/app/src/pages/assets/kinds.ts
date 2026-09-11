import type { AssetKind, ValuationSource } from "../../api/assets";

export const ASSET_KIND_OPTIONS: { value: AssetKind; label: string }[] = [
  { value: "property", label: "House or apartment" },
  { value: "land", label: "Land" },
  { value: "vehicle", label: "Vehicle" },
  { value: "valuable", label: "Jewellery or valuables" },
  { value: "business", label: "Business stake" },
  { value: "other", label: "Something else" },
];

export const ASSET_KIND_LABELS: Record<AssetKind, string> = Object.fromEntries(
  ASSET_KIND_OPTIONS.map((o) => [o.value, o.label]),
) as Record<AssetKind, string>;

export const VALUATION_SOURCE_OPTIONS: { value: ValuationSource; label: string }[] = [
  { value: "owner", label: "My own estimate" },
  { value: "professional", label: "Professional valuation" },
  { value: "market", label: "Market listing or index" },
  { value: "purchase", label: "What it cost" },
];
