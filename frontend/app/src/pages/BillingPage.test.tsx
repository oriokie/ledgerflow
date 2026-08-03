import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Subscription } from "../api/types";

const retryMutate = vi.fn();
const subState: { value: Subscription | null } = { value: null };

function makeSub(status: Subscription["status"]): Subscription {
  return {
    id: "s1",
    plan: {
      id: "p1", tier: "plus", name: "Plus", description: "", price_minor: 900, currency: "USD",
      interval: "monthly", max_members: 5, max_accounts: 25, ai_insights: true, features: [],
      resolved_features: [],
    },
    status,
    is_current: true,
    current_period_start: null,
    current_period_end: null,
    cancel_at_period_end: false,
    canceled_at: null,
    trial_end: null,
    provider: "stripe",
  } as Subscription;
}

vi.mock("../hooks/useBilling", () => ({
  usePlans: () => ({ data: [] }),
  useSubscription: () => ({ data: subState.value }),
  usePaymentMethods: () => ({ data: [] }),
  usePayments: () => ({ data: [] }),
  useSubscribe: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useCancelSubscription: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useRetrySubscription: () => ({ mutateAsync: retryMutate, isPending: false }),
  useAddPaymentMethod: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSetDefaultPaymentMethod: () => ({ mutate: vi.fn(), isPending: false }),
  useRemovePaymentMethod: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("../hooks/useFinance", () => ({ useAccounts: () => ({ data: [] }) }));
vi.mock("../hooks/useTenancy", () => ({ useMembers: () => ({ data: [] }) }));
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { role: "owner", tenant: { id: "t1", name: "Home" } } }),
}));

import { BillingPage } from "./BillingPage";

beforeEach(() => {
  retryMutate.mockReset();
  retryMutate.mockResolvedValue(makeSub("active"));
});

describe("BillingPage dunning", () => {
  it("prompts recovery and retries payment when past due", async () => {
    subState.value = makeSub("past_due");
    render(<BillingPage />);

    expect(screen.getByText(/didn't go through/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry payment/i }));
    await waitFor(() => expect(retryMutate).toHaveBeenCalled());
  });

  it("does not show a retry prompt for a healthy active subscription", () => {
    subState.value = makeSub("active");
    render(<BillingPage />);
    expect(screen.queryByRole("button", { name: /retry payment/i })).not.toBeInTheDocument();
  });
});
