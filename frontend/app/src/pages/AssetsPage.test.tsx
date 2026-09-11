import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AssetSummary, TangibleAsset } from "../api/assets";

let assets: TangibleAsset[] = [];
let summary: AssetSummary | null = null;

vi.mock("../hooks/useAssets", () => ({
  useAssets: () => ({ data: assets, isLoading: false }),
  useAssetSummary: () => ({ data: summary }),
  useAsset: () => ({ data: undefined, isLoading: false }),
  useCreateAsset: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateAsset: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteAsset: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRecordValuation: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("../hooks/useFinance", () => ({
  useAccounts: () => ({ data: [] }),
}));

vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { role: "owner", tenant: { id: "t1", base_currency: "USD" } } }),
}));

import { AssetsPage } from "./AssetsPage";

const house: TangibleAsset = {
  id: "a1",
  asset_id: "a1",
  name: "The house on Riverside",
  kind: "property",
  currency: "USD",
  description: "",
  acquired_on: "2019-06-01",
  acquisition_cost_minor: 400_000_00,
  value_minor: 800_000_00,
  valued_on: "2026-01-01",
  valuation_source: "owner",
  valuation_count: 1,
  secured_debt_account_id: null,
  secured_debt_name: null,
  debt_minor: 0,
  include_in_net_worth: true,
  equity_minor: 800_000_00,
  loan_to_value_pct: null,
  gain_minor: 400_000_00,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <AssetsPage />
    </MemoryRouter>,
  );
}

describe("AssetsPage", () => {
  beforeEach(() => {
    assets = [];
    summary = null;
  });

  it("invites a first recording when nothing is on the books", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Property" })).toBeInTheDocument();
    expect(screen.getByText(/omits the house/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add your first asset/i })).toBeInTheDocument();
  });

  it("shows worth, equity, and each recorded asset", () => {
    assets = [house];
    summary = {
      currency: "USD",
      value_minor: 800_000_00,
      debt_minor: 0,
      equity_minor: 800_000_00,
      count: 1,
      unvalued_count: 0,
    };
    renderPage();

    expect(screen.getByText("The house on Riverside")).toBeInTheDocument();
    expect(screen.getByText("House or apartment")).toBeInTheDocument();
    expect(screen.getByText("Worth")).toBeInTheDocument();
    expect(screen.getByText("Your equity")).toBeInTheDocument();
  });
});
