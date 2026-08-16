import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { RecurringTransaction } from "../../api/types";
import { SubscriptionRow } from "./SubscriptionRow";

function rec(over: Partial<RecurringTransaction> = {}): RecurringTransaction {
  return {
    id: "r1",
    txn_type: "expense",
    amount_minor: 1500,
    currency: "USD",
    frequency: "monthly",
    interval: 1,
    next_run_on: "2026-02-01",
    starts_on: "2026-01-01",
    ends_on: null,
    occurrences_created: 1,
    is_active: true,
    memo: "Netflix",
    category_id: null,
    financial_account_id: null,
    payee_id: null,
    ...over,
  };
}

function setup(over: Partial<{ onSetActive: ReturnType<typeof vi.fn>; onCancel: ReturnType<typeof vi.fn> }> = {}, recOver = {}) {
  const onSetActive = over.onSetActive ?? vi.fn().mockResolvedValue(undefined);
  const onCancel = over.onCancel ?? vi.fn().mockResolvedValue(undefined);
  render(<SubscriptionRow rec={rec(recOver)} categories={[]} onSetActive={onSetActive} onCancel={onCancel} />);
  return { onSetActive, onCancel };
}

describe("SubscriptionRow", () => {
  it("shows the label and normalized monthly cost", () => {
    setup();
    expect(screen.getByText("Netflix")).toBeInTheDocument();
    // Money renders the cents in their own span (see Money's ".lf-amount-cents"
    // convention, ui/Figure.test.tsx), so the figure is split across nodes —
    // check the whole row's text rather than a single getByText string match.
    expect(document.querySelector(".lf-sub-cost-main")?.textContent).toBe("$15.00/mo");
  });

  it("shows a quarterly block without spreading it per month", () => {
    setup({}, { frequency: "monthly", interval: 3, amount_minor: 30_000, memo: "Insurance" });
    expect(document.querySelector(".lf-sub-cost-main")?.textContent).toBe("$300.00");
  });

  it("pauses an active schedule", async () => {
    const { onSetActive } = setup();
    fireEvent.click(screen.getByRole("button", { name: /pause netflix/i }));
    await waitFor(() => expect(onSetActive).toHaveBeenCalledWith("r1", false));
  });

  it("cancels only after a confirm step", async () => {
    const { onCancel } = setup();
    fireEvent.click(screen.getByRole("button", { name: /cancel netflix/i }));
    expect(onCancel).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(onCancel).toHaveBeenCalledWith("r1"));
  });
});
