import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "./Toast";
import { useToast } from "./toastContext";

function Fire({ message }: { message: string }) {
  const toast = useToast();
  return (
    <button type="button" onClick={() => toast(message)}>
      fire
    </button>
  );
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("ToastProvider", () => {
  it("announces confirmations in a polite live region and auto-dismisses", () => {
    render(
      <ToastProvider>
        <Fire message="Marked as paid" />
      </ToastProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "fire" }));
    const viewport = screen.getByRole("status");
    expect(viewport).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("Marked as paid")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(4000);
    });
    expect(screen.queryByText("Marked as paid")).not.toBeInTheDocument();
  });

  it("keeps at most three toasts on screen", () => {
    render(
      <ToastProvider>
        <Fire message="Ping" />
      </ToastProvider>,
    );
    const btn = screen.getByRole("button", { name: "fire" });
    for (let i = 0; i < 5; i++) fireEvent.click(btn);
    expect(screen.getAllByText("Ping")).toHaveLength(3);
  });

  it("useToast is a safe no-op without a provider", () => {
    render(<Fire message="Nowhere" />);
    expect(() => fireEvent.click(screen.getByRole("button", { name: "fire" }))).not.toThrow();
  });
});
