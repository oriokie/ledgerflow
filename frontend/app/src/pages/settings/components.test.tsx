import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { SettingsAdvanced, SettingsNav, SettingsRow } from "./components";

describe("SettingsRow", () => {
  it("shows title + description and associates its label with the control", () => {
    render(
      <SettingsRow title="Theme" description="Light or dark" htmlFor="theme-input">
        <input id="theme-input" />
      </SettingsRow>,
    );
    expect(screen.getByText("Theme")).toBeInTheDocument();
    expect(screen.getByText("Light or dark")).toBeInTheDocument();
    expect(screen.getByLabelText("Theme")).toBe(document.getElementById("theme-input"));
  });
});

describe("SettingsAdvanced", () => {
  it("keeps advanced options discoverable but collapsed until opened", () => {
    render(
      <SettingsAdvanced label="Advanced options">
        <button>Danger action</button>
      </SettingsAdvanced>,
    );
    // Discoverable: the labelled toggle is present...
    const toggle = screen.getByRole("button", { name: /advanced options/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // ...but its contents are hidden by default.
    expect(screen.queryByText("Danger action")).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Danger action")).toBeInTheDocument();
  });
});

describe("SettingsNav", () => {
  it("renders grouped, linked sections", () => {
    render(
      <MemoryRouter initialEntries={["/settings/security"]}>
        <SettingsNav />
      </MemoryRouter>,
    );
    expect(screen.getByText("Your account")).toBeInTheDocument();
    expect(screen.getByText("Whole workspace")).toBeInTheDocument();
    const security = screen.getByRole("link", { name: /security/i });
    expect(security).toHaveAttribute("href", "/settings/security");
    expect(security.className).toMatch(/is-active/);
  });
});
