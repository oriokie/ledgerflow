import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { HoldingValuation, Security } from "../../api/types";

const mutateAsync = vi.fn();
vi.mock("../../hooks/useInvestments", () => ({
  useTrade: () => ({ mutateAsync }),
}));
vi.mock("../../hooks/useFinance", () => ({
  useAccounts: () => ({
    data: [
      { id: "acct-1", name: "Brokerage", account_type: "investment", currency: "USD" },
      { id: "acct-2", name: "Checking", account_type: "checking", currency: "USD" },
    ],
  }),
}));

import { TradeModal } from "./TradeModal";

const SECURITY: Security = {
  id: "sec-1",
  symbol: "ACME",
  name: "Acme Inc",
  asset_class: "stock",
  sector: "Technology",
  currency: "USD",
  exchange: "",
};

const HOLDING: HoldingValuation = {
  holding_id: "h1",
  account_id: "acct-1",
  account_name: "Brokerage",
  security_id: "sec-1",
  symbol: "ACME",
  security_name: "Acme Inc",
  asset_class: "stock",
  sector: "Technology",
  currency: "USD",
  quantity: "10",
  cost_basis_minor: 50_000,
  price_minor: 7_500,
  market_value_minor: 75_000,
  unrealized_gain_minor: 25_000,
  unrealized_gain_pct: 50,
  priced_as_of: "2026-08-03",
  is_priced: true,
};

function renderModal(props: Partial<React.ComponentProps<typeof TradeModal>> = {}) {
  return render(
    <TradeModal
      open
      action="buy"
      onClose={vi.fn()}
      securities={[SECURITY]}
      holdings={[HOLDING]}
      {...props}
    />,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("TradeModal", () => {
  it("asks for a total, not a unit price", () => {
    // A contract note shows a total; deriving it from a rounded unit price
    // would disagree with the cash that actually moved.
    renderModal();
    expect(screen.getByText("Total amount")).toBeInTheDocument();
    expect(screen.queryByText(/price per unit/i)).not.toBeInTheDocument();
  });

  it("explains that fees are capitalised on a buy", () => {
    renderModal({ action: "buy" });
    expect(screen.getByText(/added to what the position cost you/i)).toBeInTheDocument();
  });

  it("explains that fees reduce proceeds on a sell", () => {
    renderModal({ action: "sell" });
    expect(screen.getByText(/deducted from the proceeds/i)).toBeInTheDocument();
  });

  it("only offers investment accounts", () => {
    renderModal();
    const select = screen.getByLabelText(/account/i) as HTMLSelectElement;
    const labels = [...select.options].map((o) => o.textContent);
    expect(labels).toContain("Brokerage");
    // A checking account can't hold securities.
    expect(labels).not.toContain("Checking");
  });

  it("narrows the security picker to open positions when selling", () => {
    const other: Security = { ...SECURITY, id: "sec-2", symbol: "OTHER", name: "Other Co" };
    renderModal({ action: "sell", securities: [SECURITY, other] });
    const select = screen.getByLabelText(/security/i) as HTMLSelectElement;
    const labels = [...select.options].map((o) => o.textContent ?? "");
    expect(labels.some((l) => l.includes("ACME"))).toBe(true);
    // Selling something you don't hold is not a meaningful action.
    expect(labels.some((l) => l.includes("OTHER"))).toBe(false);
  });

  it("says what is held, so the common sell error is caught before the server", async () => {
    const user = userEvent.setup();
    renderModal({ action: "sell" });
    await user.selectOptions(screen.getByLabelText(/security/i), "sec-1");
    expect(screen.getByText(/you hold 10 units of acme/i)).toBeInTheDocument();
  });

  it("explains there is nothing to sell when no positions exist", () => {
    renderModal({ action: "sell", holdings: [] });
    expect(screen.getByText(/don't hold anything yet/i)).toBeInTheDocument();
  });

  it("converts entered amounts to minor units on submit", async () => {
    const user = userEvent.setup();
    mutateAsync.mockResolvedValue({});
    renderModal();

    await user.selectOptions(screen.getByLabelText(/account/i), "acct-1");
    await user.selectOptions(screen.getByLabelText(/security/i), "sec-1");
    await user.type(screen.getByLabelText(/units/i), "10");
    await user.type(screen.getByLabelText(/total amount/i), "500.00");
    await user.type(screen.getByLabelText(/fees/i), "4.95");
    await user.click(screen.getByRole("button", { name: /record purchase/i }));

    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        action: "buy",
        payload: expect.objectContaining({ amount_minor: 50_000, fee_minor: 495 }),
      }),
    );
  });

  it("refuses a zero quantity", async () => {
    const user = userEvent.setup();
    renderModal();
    await user.selectOptions(screen.getByLabelText(/account/i), "acct-1");
    await user.selectOptions(screen.getByLabelText(/security/i), "sec-1");
    await user.type(screen.getByLabelText(/units/i), "0");
    await user.type(screen.getByLabelText(/total amount/i), "100");
    await user.click(screen.getByRole("button", { name: /record purchase/i }));

    expect(await screen.findByText(/units must be greater than zero/i)).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
  });
});
