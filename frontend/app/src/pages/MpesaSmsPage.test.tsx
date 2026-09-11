import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../hooks/useFinance", () => ({
  useCategories: () => ({
    data: [{ id: "g", name: "Groceries", kind: "expense" as const, path: "Groceries", depth: 0, parent_id: null }],
  }),
  useUpdateTransaction: () => ({ mutate: vi.fn() }),
}));

const mutateAsync = vi.fn();
vi.mock("../hooks/useMpesaSms", () => ({
  useCaptureMpesaSms: () => ({ mutateAsync, isPending: false }),
  useMpesaSmsCaptures: () => ({ data: [] }),
}));

vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { role: "owner", tenant: { id: "t1", base_currency: "KES" } } }),
}));

const toast = vi.fn();
vi.mock("../ui/toastContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../ui/toastContext")>();
  return { ...actual, useToast: () => toast };
});

import { MpesaSmsPage } from "./MpesaSmsPage";

const SAMPLE =
  "UI94368KUX Confirmed. Ksh250.00 sent to JOHN  NDUNGU 0707750700 on 9/9/26 at 3:29 PM. New M-PESA balance is Ksh0.00. Transaction cost, Ksh7.00.";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MpesaSmsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("MpesaSmsPage", () => {
  it("reads the receipt, amount and date as soon as a message is pasted", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByLabelText(/m-pesa message/i));
    await user.paste(SAMPLE);

    expect(screen.getByText("UI94368KUX")).toBeInTheDocument();
    expect(screen.getByLabelText(/purpose/i)).toHaveValue("JOHN NDUNGU");
    expect(screen.getByRole("button", { name: /save to m-pesa/i })).toBeEnabled();
  });

  it("saves with the pasted message and optional purpose", async () => {
    const user = userEvent.setup();
    mutateAsync.mockResolvedValue({
      receipt: "UI94368KUX",
      account_name: "M-Pesa",
      already_recorded: false,
    });
    renderPage();

    await user.click(screen.getByLabelText(/m-pesa message/i));
    await user.paste(SAMPLE);
    await user.click(screen.getByRole("button", { name: /save to m-pesa/i }));

    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        message: SAMPLE,
        purpose: "JOHN NDUNGU",
        categoryId: null,
      }),
    );
  });

  it("keeps save disabled until the message parses", () => {
    renderPage();
    expect(screen.getByRole("button", { name: /save to m-pesa/i })).toBeDisabled();
  });
});
