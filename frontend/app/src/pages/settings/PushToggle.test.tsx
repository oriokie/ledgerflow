import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const publicKey = vi.fn();
vi.mock("../../hooks/usePush", () => ({
  usePushPublicKey: () => ({ data: publicKey(), isLoading: false }),
  usePushSubscriptionState: () => subscriptionState(),
  useTogglePush: () => ({ subscribe, unsubscribe }),
}));

const subscriptionState = vi.fn();
const subscribe = { mutateAsync: vi.fn(), isPending: false };
const unsubscribe = { mutateAsync: vi.fn(), isPending: false };

import { PushToggle } from "./PushToggle";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  publicKey.mockReturnValue({ public_key: "vapid-key" });
  subscriptionState.mockReturnValue({
    isSubscribed: false,
    isChecking: false,
    supported: true,
    endpoint: null,
  });
});

describe("PushToggle", () => {
  it("renders nothing when this deployment has no VAPID key configured", () => {
    // Offering a switch that can never work is worse than not mentioning it.
    publicKey.mockReturnValue(null);
    const { container } = render(<PushToggle />, { wrapper });
    expect(container).toBeEmptyDOMElement();
  });

  it("explains rather than hides the toggle when the browser lacks support", () => {
    subscriptionState.mockReturnValue({
      isSubscribed: false,
      isChecking: false,
      supported: false,
      endpoint: null,
    });
    render(<PushToggle />, { wrapper });
    expect(screen.getByText(/aren't available in this browser/i)).toBeInTheDocument();
  });

  it("reflects the browser's own subscription state, not just local memory", () => {
    // A subscription can be revoked outside the app; the toggle must show
    // reality, not drift from it.
    subscriptionState.mockReturnValue({
      isSubscribed: true,
      isChecking: false,
      supported: true,
      endpoint: "https://push.example.com/x",
    });
    render(<PushToggle />, { wrapper });
    expect(screen.getByRole("switch")).toBeChecked();
  });

  it("subscribes when turned on", async () => {
    subscribe.mutateAsync.mockResolvedValue("https://push.example.com/new");
    const user = userEvent.setup();
    render(<PushToggle />, { wrapper });

    await user.click(screen.getByRole("switch"));
    await waitFor(() => expect(subscribe.mutateAsync).toHaveBeenCalledWith("vapid-key"));
  });

  it("explains a blocked permission rather than failing silently", async () => {
    subscribe.mutateAsync.mockResolvedValue(null); // user declined the browser prompt
    const user = userEvent.setup();
    render(<PushToggle />, { wrapper });

    await user.click(screen.getByRole("switch"));
    expect(await screen.findByText(/blocked/i)).toBeInTheDocument();
  });

  it("unsubscribes when turned off", async () => {
    subscriptionState.mockReturnValue({
      isSubscribed: true,
      isChecking: false,
      supported: true,
      endpoint: "https://push.example.com/x",
    });
    const user = userEvent.setup();
    render(<PushToggle />, { wrapper });

    await user.click(screen.getByRole("switch"));
    await waitFor(() => expect(unsubscribe.mutateAsync).toHaveBeenCalled());
  });

  it("disables the switch while checking the browser's current state", () => {
    subscriptionState.mockReturnValue({
      isSubscribed: false,
      isChecking: true,
      supported: true,
      endpoint: undefined,
    });
    render(<PushToggle />, { wrapper });
    expect(screen.getByRole("switch")).toBeDisabled();
  });
});
