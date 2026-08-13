import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FinancialAccount } from "../api/types";

const accounts: FinancialAccount[] = [
  { id: "chk", name: "Checking", account_type: "checking", currency: "USD", balance_minor: 0 },
];
const categories = [{ id: "g", name: "Groceries", kind: "expense" as const }];

vi.mock("../hooks/useFinance", () => ({
  useAccounts: () => ({ data: accounts }),
  useCategories: () => ({ data: categories }),
  // No signal beyond `accounts`/the receipt itself in these tests — the page
  // falls back to accounts[0] when this resolves nothing, which is enough to
  // exercise the "guessed" hint without needing real transaction history here.
  useTransactions: () => ({ data: undefined }),
}));
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { role: "owner", tenant: { id: "t1", base_currency: "USD" } } }),
}));

vi.mock("../components/receipts/ReceiptCamera", () => ({
  ReceiptCamera: ({ onCapture }: { onCapture: (file: Blob) => void }) => (
    <button onClick={() => onCapture(new Blob(["x"], { type: "image/jpeg" }))}>Simulate capture</button>
  ),
}));

const captureMutateAsync = vi.fn();
const confirmFieldsMutateAsync = vi.fn();
const linkMutateAsync = vi.fn();
const discardMutateAsync = vi.fn();

vi.mock("../hooks/useReceipts", () => ({
  useCaptureReceipt: () => ({ mutateAsync: captureMutateAsync }),
  useReceipt: (id: string | null) => ({
    data: id
      ? {
          id,
          status: "parsed",
          confidence: 0.9,
          confirmed_merchant: "Corner Shop",
          confirmed_amount_minor: 1250,
          confirmed_occurred_on: "2026-06-01",
        }
      : undefined,
    isLoading: false,
  }),
  useConfirmReceiptFields: () => ({ mutateAsync: confirmFieldsMutateAsync, isPending: false }),
  useLinkReceipt: () => ({ mutateAsync: linkMutateAsync, isPending: false }),
  useDiscardReceipt: () => ({ mutateAsync: discardMutateAsync }),
}));

const toast = vi.fn();
vi.mock("../ui/toastContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../ui/toastContext")>();
  return { ...actual, useToast: () => toast };
});

import { ReceiptScanPage } from "./ReceiptScanPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <ReceiptScanPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  captureMutateAsync.mockResolvedValue({ id: "r1", status: "uploaded" });
});

describe("ReceiptScanPage", () => {
  it("opens directly into the camera", () => {
    renderPage();
    expect(screen.getByRole("button", { name: /simulate capture/i })).toBeInTheDocument();
  });

  it("pre-fills the confirmation form from what OCR read", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /simulate capture/i }));

    const merchantInput = await screen.findByLabelText(/^merchant/i);
    expect((merchantInput as HTMLInputElement).value).toBe("Corner Shop");
    expect((screen.getByLabelText(/^amount/i) as HTMLInputElement).value).toBe("12.5");
  });

  it("every pre-filled field is an editable input, not a fact", async () => {
    // The governing rule of the whole receipts app, checked at the UI layer:
    // OCR guesses are never presented as already-true.
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /simulate capture/i }));

    const merchantInput = (await screen.findByLabelText(/^merchant/i)) as HTMLInputElement;
    expect(merchantInput).not.toBeDisabled();
    expect(merchantInput.tagName).toBe("INPUT");
  });

  it("warns when OCR confidence is low", async () => {
    vi.doMock("../hooks/useReceipts", () => ({
      useCaptureReceipt: () => ({ mutateAsync: captureMutateAsync }),
      useReceipt: () => ({
        data: {
          id: "r1",
          status: "parsed",
          confidence: 0.3,
          confirmed_merchant: "",
          confirmed_amount_minor: null,
          confirmed_occurred_on: null,
        },
        isLoading: false,
      }),
      useConfirmReceiptFields: () => ({ mutateAsync: confirmFieldsMutateAsync, isPending: false }),
      useLinkReceipt: () => ({ mutateAsync: linkMutateAsync, isPending: false }),
      useDiscardReceipt: () => ({ mutateAsync: discardMutateAsync }),
    }));
    vi.resetModules();
    const { ReceiptScanPage: FreshPage } = await import("./ReceiptScanPage");
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <FreshPage />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: /simulate capture/i }));
    expect(await screen.findByText(/may not be right/i)).toBeInTheDocument();
  });

  it("requires an account and category before adding", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /simulate capture/i }));
    await screen.findByLabelText(/^merchant/i);

    expect(screen.getByRole("button", { name: /add transaction/i })).toBeDisabled();
  });

  it("links the receipt using the confirmed fields once everything is chosen", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /simulate capture/i }));
    await screen.findByLabelText(/^merchant/i);

    await user.selectOptions(screen.getByLabelText(/^account/i), "chk");
    await user.selectOptions(screen.getByLabelText(/^category/i), "g");
    await user.click(screen.getByRole("button", { name: /add transaction/i }));

    await waitFor(() => expect(linkMutateAsync).toHaveBeenCalled());
    expect(linkMutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ receiptId: "r1", financialAccountId: "chk", categoryId: "g" }),
    );
  });

  it("discarding never links a transaction", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /simulate capture/i }));
    await screen.findByLabelText(/^merchant/i);

    await user.click(screen.getByRole("button", { name: /discard/i }));

    await waitFor(() => expect(discardMutateAsync).toHaveBeenCalledWith("r1"));
    expect(linkMutateAsync).not.toHaveBeenCalled();
  });

  it("returns to the camera after discarding, for the next receipt", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /simulate capture/i }));
    await screen.findByLabelText(/^merchant/i);
    await user.click(screen.getByRole("button", { name: /discard/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /simulate capture/i })).toBeInTheDocument(),
    );
  });
});
