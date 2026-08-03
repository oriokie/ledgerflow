/**
 * Accessibility audit of the mobile surfaces added in this work.
 *
 * Automated auditing catches a real but bounded class of problem — missing
 * labels, bad roles, orphaned form controls. It cannot tell you whether focus
 * lands somewhere sensible when a camera opens, or whether a status change is
 * announced. Those are checked explicitly further down rather than assumed
 * covered by axe passing.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FinancialAccount } from "../api/types";
import { describeViolations, findViolations } from "../test/a11y";

// ---------------------------------------------------------------- mocks
const accounts: FinancialAccount[] = [
  { id: "chk", name: "Checking", account_type: "checking", currency: "USD", balance_minor: 0 },
];

vi.mock("../hooks/useFinance", () => ({
  useAccounts: () => ({ data: accounts }),
  useCategories: () => ({ data: [{ id: "g", name: "Groceries", kind: "expense" as const }] }),
}));
vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ activeWorkspace: { role: "owner", tenant: { id: "t1", base_currency: "USD" } } }),
}));
vi.mock("../hooks/useQuickAdd", () => ({
  useQuickAdd: () => ({ mutateAsync: vi.fn().mockResolvedValue({ queued: false, result: null }), isPending: false }),
  usePendingQuickAddCount: () => 0,
}));

const pendingCount = vi.fn(() => 0);
vi.mock("../hooks/useReceipts", () => ({
  useCaptureReceipt: () => ({ mutateAsync: vi.fn().mockResolvedValue({ id: "r1" }) }),
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
  useConfirmReceiptFields: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useLinkReceipt: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDiscardReceipt: () => ({ mutateAsync: vi.fn() }),
}));

import { ReceiptCamera } from "../components/receipts/ReceiptCamera";
import { OfflineIndicator } from "../components/shell/OfflineIndicator";
import { QuickAddPage } from "./QuickAddPage";
import { ReceiptScanPage } from "./ReceiptScanPage";

const originalMediaDevices = navigator.mediaDevices;
const originalOnLine = navigator.onLine;

beforeEach(() => {
  HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
  pendingCount.mockReturnValue(0);
});

afterEach(() => {
  Object.defineProperty(navigator, "mediaDevices", { value: originalMediaDevices, configurable: true });
  Object.defineProperty(navigator, "onLine", { value: originalOnLine, configurable: true });
  vi.restoreAllMocks();
});

function stubCamera(resolve = true) {
  const track = { stop: vi.fn() };
  Object.defineProperty(navigator, "mediaDevices", {
    value: {
      getUserMedia: vi.fn(() =>
        resolve ? Promise.resolve({ getTracks: () => [track] } as unknown as MediaStream) : Promise.reject(new Error("denied")),
      ),
    },
    configurable: true,
  });
  return track;
}

// ============================================================ automated audit
describe("automated accessibility audit", () => {
  it("Quick Add page has no violations", async () => {
    const { container } = render(
      <MemoryRouter>
        <QuickAddPage />
      </MemoryRouter>,
    );
    const violations = await findViolations(container);
    expect(violations, describeViolations(violations)).toHaveLength(0);
  });

  it("receipt confirmation form has no violations", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <MemoryRouter>
        <ReceiptScanPage />
      </MemoryRouter>,
    );
    // The page opens into the camera; step through to the form under audit.
    stubCamera(false); // fall back to the file-picker view, then simulate
    await user.click(screen.getByRole("button", { name: /choose photo/i }).closest("button")!);

    const violations = await findViolations(container);
    expect(violations, describeViolations(violations)).toHaveLength(0);
  });

  it("camera view has no violations", async () => {
    stubCamera();
    const { container } = render(<ReceiptCamera onCapture={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: /take photo/i })).toBeInTheDocument());

    const violations = await findViolations(container);
    expect(violations, describeViolations(violations)).toHaveLength(0);
  });

  it("camera fallback view has no violations", async () => {
    Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
    const { container } = render(<ReceiptCamera onCapture={vi.fn()} onClose={vi.fn()} />);
    await screen.findByRole("button", { name: /choose photo/i });

    const violations = await findViolations(container);
    expect(violations, describeViolations(violations)).toHaveLength(0);
  });

  it("offline indicator has no violations", async () => {
    Object.defineProperty(navigator, "onLine", { value: false, configurable: true });
    const { container } = render(<OfflineIndicator />);
    const violations = await findViolations(container);
    expect(violations, describeViolations(violations)).toHaveLength(0);
  });
});

// ================================================ what axe structurally cannot check
describe("focus management", () => {
  it("moves focus into the camera when it opens", async () => {
    // Without this, a keyboard or screen-reader user is left with focus on
    // whatever triggered the camera — a control now hidden behind a
    // full-screen overlay they have no idea they're inside.
    stubCamera();
    render(<ReceiptCamera onCapture={vi.fn()} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(document.activeElement).not.toBe(document.body);
      expect(document.activeElement?.closest(".lf-camera, .lf-camera-fallback")).not.toBeNull();
    });
  });

  it("keeps Escape available to leave the camera", async () => {
    stubCamera();
    const onClose = vi.fn();
    render(<ReceiptCamera onCapture={vi.fn()} onClose={onClose} />);
    await waitFor(() => expect(screen.getByRole("button", { name: /take photo/i })).toBeInTheDocument());

    await userEvent.setup().keyboard("{Escape}");
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

describe("status announcements", () => {
  it("announces the offline state politely, not assertively", () => {
    // `role="status"` is implicitly aria-live=polite: connectivity is worth
    // knowing but never worth interrupting someone mid-sentence for.
    Object.defineProperty(navigator, "onLine", { value: false, configurable: true });
    render(<OfflineIndicator />);
    const status = screen.getByRole("status");
    expect(status).toBeInTheDocument();
    expect(status.getAttribute("aria-live")).not.toBe("assertive");
  });
});
