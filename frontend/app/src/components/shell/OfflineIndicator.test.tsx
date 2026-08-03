import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pendingCount = vi.fn();
vi.mock("../../hooks/useQuickAdd", () => ({
  usePendingQuickAddCount: () => pendingCount(),
}));

import { OfflineIndicator } from "./OfflineIndicator";

function setOnlineStatus(value: boolean) {
  Object.defineProperty(navigator, "onLine", { value, configurable: true });
}

const originalOnLine = navigator.onLine;
beforeEach(() => {
  pendingCount.mockReturnValue(0);
  setOnlineStatus(true);
});
afterEach(() => setOnlineStatus(originalOnLine));

describe("OfflineIndicator", () => {
  it("renders nothing in the common case — online, nothing queued", () => {
    // A permanent "you're online" bar is exactly the kind of thing nobody
    // needs to see and everyone learns to tune out.
    const { container } = render(<OfflineIndicator />);
    expect(container).toBeEmptyDOMElement();
  });

  it("appears when the connection is lost", () => {
    setOnlineStatus(false);
    render(<OfflineIndicator />);
    expect(screen.getByRole("status")).toHaveTextContent(/you're offline/i);
  });

  it("mentions how many entries are waiting while offline", () => {
    setOnlineStatus(false);
    pendingCount.mockReturnValue(3);
    render(<OfflineIndicator />);
    expect(screen.getByRole("status")).toHaveTextContent(/3 entries will send/i);
  });

  it("uses correct singular phrasing for exactly one entry", () => {
    setOnlineStatus(false);
    pendingCount.mockReturnValue(1);
    render(<OfflineIndicator />);
    expect(screen.getByRole("status")).toHaveTextContent(/1 entry will send/i);
  });

  it("shows a sending state when back online with a queue still draining", () => {
    setOnlineStatus(true);
    pendingCount.mockReturnValue(2);
    render(<OfflineIndicator />);
    expect(screen.getByRole("status")).toHaveTextContent(/sending 2 queued entries/i);
  });

  it("reacts to the browser's online/offline events, not just the initial state", async () => {
    render(<OfflineIndicator />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    setOnlineStatus(false);
    window.dispatchEvent(new Event("offline"));
    await waitFor(() => expect(screen.getByRole("status")).toBeInTheDocument());

    setOnlineStatus(true);
    window.dispatchEvent(new Event("online"));
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  });
});
