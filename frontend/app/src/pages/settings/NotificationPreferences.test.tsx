import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NotificationPreferences } from "../../api/notifications";

const prefs: { value: NotificationPreferences } = {
  value: {
    muted_types: [],
    email_enabled: false,
    email_types: [],
    push_enabled: true,
    monthly_summary: true,
    budget_threshold: 0.9,
    low_balance_minor: null,
    large_transaction_minor: null,
    available_types: [
      { value: "bill_due", label: "Bill due soon" },
      { value: "goal_milestone", label: "Goal milestone" },
    ],
    email_default_types: ["bill_due"],
  },
};
const updateSpy = vi.fn();

vi.mock("../../api/notifications", () => ({
  notificationsApi: {
    preferences: () => Promise.resolve(prefs.value),
    updatePreferences: (body: unknown) => {
      updateSpy(body);
      return Promise.resolve({ ...prefs.value, ...(body as object) });
    },
  },
}));

import { NotificationPreferencesSection } from "./NotificationPreferences";

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NotificationPreferencesSection />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  updateSpy.mockClear();
  prefs.value = { ...prefs.value, muted_types: [], email_enabled: false, email_types: [] };
});

describe("NotificationPreferencesSection", () => {
  it("offers a per-type matrix, not one master switch", async () => {
    renderPanel();
    // The whole point: "everything off" was previously the only answer to
    // "these alerts are noisy".
    expect(await screen.findByLabelText("Bill due soon in app")).toBeInTheDocument();
    expect(screen.getByLabelText("Goal milestone in app")).toBeInTheDocument();
  });

  it("mutes a single type without touching the others", async () => {
    renderPanel();
    fireEvent.click(await screen.findByLabelText("Goal milestone in app"));
    await waitFor(() => expect(updateSpy).toHaveBeenCalledWith({ muted_types: ["goal_milestone"] }));
  });

  it("disables email switches until email is enabled", async () => {
    renderPanel();
    expect(await screen.findByLabelText("Bill due soon by email")).toBeDisabled();
  });

  it("disables the email switch for a type that is muted entirely", async () => {
    // Muting mutes everywhere, so offering an email choice would be a lie.
    prefs.value = { ...prefs.value, email_enabled: true, muted_types: ["bill_due"] };
    renderPanel();
    expect(await screen.findByLabelText("Bill due soon by email")).toBeDisabled();
  });

  it("says the monthly summary needs email on", async () => {
    renderPanel();
    expect(await screen.findByText(/needs email switched on/i)).toBeInTheDocument();
  });

  it("sends the resolved email list, not a diff", async () => {
    prefs.value = { ...prefs.value, email_enabled: true };
    renderPanel();
    fireEvent.click(await screen.findByLabelText("Goal milestone by email"));
    // Defaults were ["bill_due"]; adding one must preserve it, or switching a
    // type on would silently drop the defaults.
    await waitFor(() =>
      expect(updateSpy).toHaveBeenCalledWith({ email_types: ["bill_due", "goal_milestone"] }),
    );
  });
});
