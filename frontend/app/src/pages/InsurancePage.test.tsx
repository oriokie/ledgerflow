import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { InsurancePolicy, InsuranceSummary } from "../api/insurance";

let policies: InsurancePolicy[] = [];
let summary: InsuranceSummary | null = null;

vi.mock("../hooks/useInsurance", () => ({
  usePolicies: () => ({ data: policies, isLoading: false }),
  useInsuranceSummary: () => ({ data: summary }),
  usePolicy: () => ({ data: undefined, isLoading: false }),
  useCreatePolicy: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdatePolicy: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeletePolicy: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("../hooks/useAssets", () => ({
  useAssets: () => ({ data: [] }),
}));

vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { role: "owner", tenant: { id: "t1", base_currency: "USD" } } }),
}));

import { InsurancePage } from "./InsurancePage";

const home: InsurancePolicy = {
  id: "p1",
  policy_id: "p1",
  name: "Buildings cover",
  kind: "home",
  insurer: "UAP",
  currency: "USD",
  coverage_minor: 400_000_00,
  deductible_minor: null,
  premium_minor: 12_000_00,
  premium_frequency: "annual",
  annual_premium_minor: 12_000_00,
  monthly_premium_minor: 1_000_00,
  renews_on: "2027-01-01",
  ends_on: null,
  covers_asset_id: "a1",
  covers_asset_name: "The house",
  asset_value_minor: 800_000_00,
  coverage_gap_minor: -400_000_00,
  covers_account_id: null,
  covers_account_name: null,
  bill_id: null,
  recurring_transaction_id: null,
  premium_in_cashflow: false,
  is_active: true,
  notes: "",
  underinsured: true,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <InsurancePage />
    </MemoryRouter>,
  );
}

describe("InsurancePage", () => {
  beforeEach(() => {
    policies = [];
    summary = null;
  });

  it("invites a first policy when nothing is recorded", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "Insurance" })).toBeInTheDocument();
    expect(screen.getByText(/no policies recorded/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add your first policy/i })).toBeInTheDocument();
  });

  it("shows annual premium and each recorded policy", () => {
    policies = [home];
    summary = {
      currency: "USD",
      count: 1,
      annual_premium_minor: 12_000_00,
      underinsured_count: 1,
      unlinked_count: 1,
    };
    renderPage();
    expect(screen.getByText("Buildings cover")).toBeInTheDocument();
    expect(screen.getByText(/cover is below/i)).toBeInTheDocument();
  });
});
