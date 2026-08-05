import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DebtSummary, DebtView } from "../api/types";

const summary = vi.fn();
const debts = vi.fn();
const trackedState: { value: unknown[] } = { value: [] };

vi.mock("../hooks/useDebt", () => ({
  useDebtSummary: () => ({ data: summary(), isLoading: false }),
  useTrackedLiabilities: () => ({ data: trackedState.value }),
  useDebts: () => ({ data: debts() }),
  useDebtStress: () => ({ data: undefined }),
  useBorrowingCost: () => ({ data: undefined }),
  useDebtAnalytics: () => ({ data: undefined }),
  usePayoffPlan: () => ({ data: undefined }),
  useSetDebtTerms: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSimulateRefinance: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useCreateDebt: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteDebt: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock("../api/debt", () => ({
  debtApi: { exportUrl: () => "/export.csv" },
}));
// The create-debt form defaults its currency to the workspace's.
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({
    activeWorkspace: { role: "owner", tenant: { id: "t1", base_currency: "USD" } },
  }),
}));

import { DebtPage } from "./DebtPage";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/debt"]}>
        <Routes>
          <Route path="/debt" element={children} />
          <Route path="/accounts" element={<p>Accounts page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const SUMMARY: DebtSummary = {
  currency: "USD",
  total_balance_minor: 500_000,
  total_minimum_minor: 20_000,
  total_monthly_interest_minor: 8_000,
  annual_interest_minor: 96_000,
  debt_count: 1,
  weighted_apr: 19.9,
  highest_apr_name: "Card",
  highest_apr: 19.9,
  unplannable_count: 0,
  growing_count: 0,
  priced_count: 1,
  alerts: [],
  recommendation: null,
};

const DEBT: DebtView = {
  account_id: "d1",
  name: "Card",
  currency: "USD",
  debt_kind: "credit_card",
  balance_minor: 500_000,
  apr: 19.9,
  minimum_payment_minor: 20_000,
  payment_day: null,
  monthly_interest_minor: 8_000,
  minimum_covers_interest: true,
  original_principal_minor: null,
  percent_repaid: null,
  include_in_payoff: true,
  has_terms: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  debts.mockReturnValue([]);
});


describe("DebtPage — empty state", () => {
  it("offers a real way forward rather than a dead end", () => {
    // Regression: this page's PageHeader had no `actions` prop and its
    // EmptyState had no `action` prop at all — a first-time visitor saw a
    // title, a description, and static tips with nothing clickable on the
    // whole page. Every other page's equivalent empty state (Investments,
    // Goals) has a CTA; this one didn't.
    summary.mockReturnValue(undefined);
    render(<DebtPage />, { wrapper });

    expect(screen.getByRole("button", { name: /add a debt/i })).toBeInTheDocument();
  });

  it("the CTA opens the debt form rather than bouncing to the accounts page", async () => {
    // Regression: this used to navigate to /accounts?add=1, which made a bare
    // account with no terms and left the planner still empty — so the button
    // read as broken.
    summary.mockReturnValue(undefined);
    const user = userEvent.setup();
    render(<DebtPage />, { wrapper });

    await user.click(screen.getByRole("button", { name: /add a debt/i }));
    expect(screen.getByRole("dialog", { name: /add a debt/i })).toBeInTheDocument();
    expect(screen.queryByText("Accounts page")).not.toBeInTheDocument();
  });

  it("asks only for a name and an amount, so an informal debt can be entered", async () => {
    // A loan from a friend has no APR and no minimum payment. Requiring them
    // would either block the entry or invite an invented figure.
    summary.mockReturnValue(undefined);
    const user = userEvent.setup();
    render(<DebtPage />, { wrapper });

    await user.click(screen.getByRole("button", { name: /add a debt/i }));
    const dialog = screen.getByRole("dialog", { name: /add a debt/i });
    expect(within(dialog).getByLabelText(/^name/i)).toBeRequired();
    expect(within(dialog).getByLabelText(/amount owed/i)).toBeRequired();
    expect(within(dialog).getByLabelText(/interest rate/i)).not.toBeRequired();
    expect(within(dialog).getByLabelText(/minimum payment/i)).not.toBeRequired();
  });

  it("explains that adding a debt sets up its account too", () => {
    summary.mockReturnValue(undefined);
    render(<DebtPage />, { wrapper });
    expect(screen.getByText(/sets up the account behind it/i)).toBeInTheDocument();
  });
});

describe("DebtPage — populated state", () => {
  it("renders the summary and the consolidation action without crashing", () => {
    summary.mockReturnValue(SUMMARY);
    debts.mockReturnValue([DEBT]);
    render(<DebtPage />, { wrapper });

    expect(screen.getByText("Card")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /compare a consolidation loan/i })).toBeInTheDocument();
  });

  it("disables consolidation with fewer than two termed debts", () => {
    summary.mockReturnValue(SUMMARY);
    debts.mockReturnValue([DEBT]);
    render(<DebtPage />, { wrapper });

    expect(screen.getByRole("button", { name: /compare a consolidation loan/i })).toBeDisabled();
  });
});
