import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlatformSetting } from "../../api/platform";

const staffState: { value: { capabilities: string[] } | null } = { value: null };
const settingsState: { value: PlatformSetting[] } = { value: [] };
const writeMutate = vi.fn().mockResolvedValue({});

function setting(overrides: Partial<PlatformSetting> = {}): PlatformSetting {
  return {
    key: "invoice.issuer_name",
    kind: "string",
    group: "invoicing",
    label: "Issuer name",
    help: "The legal entity that issues invoices.",
    env_setting: null,
    choices: [],
    source: "default",
    overridden: false,
    env_configured: false,
    value: "LedgerFlow",
    updated_at: null,
    updated_by: null,
    ...overrides,
  };
}

vi.mock("../../hooks/usePlatform", async () => {
  const actual = await vi.importActual<typeof import("../../hooks/usePlatform")>(
    "../../hooks/usePlatform",
  );
  return {
    ...actual,
    usePlatformMe: () => ({ data: staffState.value, isLoading: false, isError: false }),
    usePlatformSettings: () => ({ data: { settings: settingsState.value }, isLoading: false }),
    useWriteSetting: () => ({ mutateAsync: writeMutate, isPending: false }),
  };
});

import { AdminSettingsPage } from "./AdminSettingsPage";

beforeEach(() => {
  staffState.value = { capabilities: ["health.read", "staff.manage"] };
  settingsState.value = [setting()];
  writeMutate.mockClear();
});

describe("AdminSettingsPage", () => {
  it("never renders a secret's value", () => {
    // A compromised admin session must not become a credential dump.
    settingsState.value = [
      setting({
        key: "payments.stripe_secret_key",
        kind: "secret",
        group: "payments",
        label: "Stripe secret key",
        value: null,
        is_set: true,
        overridden: true,
        source: "database",
      }),
    ];
    render(<AdminSettingsPage />);

    const field = screen.getByLabelText("Stripe secret key") as HTMLInputElement;
    expect(field.type).toBe("password");
    expect(field.value).toBe("");
    expect(screen.getByText(/cannot be read back/i)).toBeInTheDocument();
  });

  it("says where each value came from", () => {
    settingsState.value = [
      // Labels deliberately distinct from the badge copy, so the assertions
      // below can only match the badges.
      setting({ key: "a", label: "Alpha", source: "environment", env_configured: true }),
      setting({ key: "b", label: "Beta", source: "database", overridden: true }),
      setting({ key: "c", label: "Gamma", source: "default" }),
    ];
    render(<AdminSettingsPage />);

    expect(screen.getByText("From environment")).toBeInTheDocument();
    expect(screen.getByText("Set here")).toBeInTheDocument();
    expect(screen.getByText("Default")).toBeInTheDocument();
  });

  it("saves an edited value", async () => {
    render(<AdminSettingsPage />);

    fireEvent.change(screen.getByLabelText("Issuer name"), { target: { value: "Acme Ltd" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(writeMutate).toHaveBeenCalledWith({ key: "invoice.issuer_name", value: "Acme Ltd" }),
    );
  });

  it("sends null to reset an override back to the environment", async () => {
    settingsState.value = [setting({ overridden: true, source: "database" })];
    render(<AdminSettingsPage />);

    fireEvent.click(screen.getByRole("button", { name: "Reset" }));

    await waitFor(() =>
      expect(writeMutate).toHaveBeenCalledWith({ key: "invoice.issuer_name", value: null }),
    );
  });

  it("offers no Reset when nothing is overridden", () => {
    render(<AdminSettingsPage />);
    expect(screen.queryByRole("button", { name: "Reset" })).not.toBeInTheDocument();
  });

  it("is read-only without the access-management capability", () => {
    staffState.value = { capabilities: ["health.read"] };
    render(<AdminSettingsPage />);

    expect(screen.getByLabelText("Issuer name")).toBeDisabled();
    expect(screen.getByText(/needs the access-management capability/i)).toBeInTheDocument();
  });

  it("coerces a numeric setting before sending it", async () => {
    settingsState.value = [
      setting({ key: "invoice.payment_terms_days", kind: "integer", label: "Terms", value: 14 }),
    ];
    render(<AdminSettingsPage />);

    fireEvent.change(screen.getByLabelText("Terms"), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(writeMutate).toHaveBeenCalledWith({ key: "invoice.payment_terms_days", value: 30 }),
    );
  });

  it("explains who controls AI", () => {
    render(<AdminSettingsPage />);
    expect(screen.getByText(/Is AI available at all\?/i)).toBeInTheDocument();
    expect(screen.getByText(/Their plan decides/i)).toBeInTheDocument();
    expect(screen.getByText(/owner can opt out/i)).toBeInTheDocument();
  });
});

describe("closed-set settings", () => {
  it("offers the choices rather than a text box", async () => {
    // A closed set rendered as free text is how somebody types "doodles" and
    // finds out from a blank page. The illustration style is platform-wide, so
    // the blank page would be everyone's.
    staffState.value = { capabilities: ["health.read", "staff.manage"] };
    settingsState.value = [
      setting({
        key: "appearance.illustration_style",
        group: "appearance",
        label: "Illustration style",
        choices: ["clay", "doodle"],
        value: "clay",
      }),
    ];
    render(<AdminSettingsPage />);

    expect(screen.getByRole("radio", { name: "Clay" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Doodle" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /illustration style/i })).not.toBeInTheDocument();
  });

  it("saves the moment a style is picked, with no separate confirm", async () => {
    staffState.value = { capabilities: ["health.read", "staff.manage"] };
    settingsState.value = [
      setting({
        key: "appearance.illustration_style",
        group: "appearance",
        label: "Illustration style",
        choices: ["clay", "doodle"],
        value: "clay",
      }),
    ];
    render(<AdminSettingsPage />);

    await userEvent.click(screen.getByRole("radio", { name: "Doodle" }));
    expect(writeMutate).toHaveBeenCalledWith(
      expect.objectContaining({ key: "appearance.illustration_style", value: "doodle" }),
    );
  });
});
