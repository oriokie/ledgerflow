import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FinancialAccount } from "../api/types";

const accounts: FinancialAccount[] = [
  { id: "chk", name: "Everyday Checking", account_type: "checking", currency: "USD", balance_minor: 250_00 },
];

vi.mock("../hooks/useFinance", () => ({
  useAccounts: () => ({ data: accounts }),
  useCategories: () => ({ data: [] }),
}));
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { role: "owner", tenant: { id: "t1", base_currency: "USD" } } }),
}));

const mutateAsync = vi.fn();
vi.mock("../hooks/useQuickAdd", () => ({
  useQuickAdd: () => ({ mutateAsync, isPending: false }),
  usePendingQuickAddCount: () => 0,
}));

const toast = vi.fn();
vi.mock("../ui/toastContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../ui/toastContext")>();
  return { ...actual, useToast: () => toast };
});

import { QuickAddPage } from "./QuickAddPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <QuickAddPage />
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("QuickAddPage", () => {
  it("requires only an amount and a merchant to submit", async () => {
    const user = userEvent.setup();
    mutateAsync.mockResolvedValue({
      queued: false,
      result: {
        transaction_id: "t1",
        financial_account_name: "Everyday Checking",
        category_name: "Groceries",
        category_was_inferred: true,
      },
    });
    renderPage();

    await user.type(screen.getByLabelText(/amount/i), "12.50");
    await user.type(screen.getByLabelText(/^to/i), "Corner Shop");
    await user.click(screen.getByRole("button", { name: /^add$/i }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ amountMinor: 1250, merchant: "Corner Shop" }),
    );
  });

  it("keeps the submit button disabled until both fields are filled", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByRole("button", { name: /^add$/i })).toBeDisabled();
    await user.type(screen.getByLabelText(/amount/i), "10");
    expect(screen.getByRole("button", { name: /^add$/i })).toBeDisabled();
  });

  it("switches the field label between spending and receiving", async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByLabelText(/^to/i)).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /received/i }));
    expect(screen.getByLabelText(/^from/i)).toBeInTheDocument();
  });

  it("shows what was inferred, and offers a way to fix it", async () => {
    const user = userEvent.setup();
    mutateAsync.mockResolvedValue({
      queued: false,
      result: {
        transaction_id: "t1",
        financial_account_name: "Everyday Checking",
        category_name: "Groceries",
        category_was_inferred: true,
      },
    });
    renderPage();

    await user.type(screen.getByLabelText(/amount/i), "12.50");
    await user.type(screen.getByLabelText(/^to/i), "Corner Shop");
    await user.click(screen.getByRole("button", { name: /^add$/i }));

    expect(await screen.findByText("Everyday Checking")).toBeInTheDocument();
    expect(screen.getByText(/fix it/i)).toBeInTheDocument();
  });

  it("does not offer a fix-it link when the category was typed explicitly", async () => {
    const user = userEvent.setup();
    mutateAsync.mockResolvedValue({
      queued: false,
      result: {
        transaction_id: "t1",
        financial_account_name: "Everyday Checking",
        category_name: "Groceries",
        category_was_inferred: false,
      },
    });
    renderPage();

    await user.type(screen.getByLabelText(/amount/i), "12.50");
    await user.type(screen.getByLabelText(/^to/i), "Corner Shop");
    await user.click(screen.getByRole("button", { name: /^add$/i }));

    await screen.findByText("Everyday Checking");
    expect(screen.queryByText(/fix it/i)).not.toBeInTheDocument();
  });

  it("confirms saved-for-later rather than an error when queued offline", async () => {
    const user = userEvent.setup();
    mutateAsync.mockResolvedValue({ queued: true, result: null });
    renderPage();

    await user.type(screen.getByLabelText(/amount/i), "5");
    await user.type(screen.getByLabelText(/^to/i), "Shop");
    await user.click(screen.getByRole("button", { name: /^add$/i }));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(expect.stringMatching(/will send/i), expect.anything()),
    );
  });

  it("clears the form after a successful submission", async () => {
    const user = userEvent.setup();
    mutateAsync.mockResolvedValue({
      queued: false,
      result: {
        transaction_id: "t1",
        financial_account_name: "Everyday Checking",
        category_name: null,
        category_was_inferred: false,
      },
    });
    renderPage();

    const amountInput = screen.getByLabelText(/amount/i) as HTMLInputElement;
    await user.type(amountInput, "5");
    await user.type(screen.getByLabelText(/^to/i), "Shop");
    await user.click(screen.getByRole("button", { name: /^add$/i }));

    await waitFor(() => expect(amountInput.value).toBe(""));
  });
});
