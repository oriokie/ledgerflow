import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "u1", email: "sam@example.com", first_name: "Sam", last_name: "Lee", mfa_enabled: false },
    activeWorkspace: {
      id: "w1",
      role: "owner",
      created_at: "2026-01-01",
      tenant: { id: "t1", name: "Family", type: "family", base_currency: "USD", default_locale: "en-US", default_timezone: "UTC" },
    },
  }),
}));

import { SettingsPage } from "./SettingsPage";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/settings/*" element={<SettingsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SettingsPage", () => {
  it("shows grouped navigation and the profile panel by default", () => {
    renderAt("/settings/profile");
    // Grouped nav
    expect(screen.getByRole("link", { name: /profile/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /security/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /categories & tags/i })).toBeInTheDocument();
    // Routed panel content
    expect(screen.getByText("sam@example.com")).toBeInTheDocument();
  });

  it("routes the workspace panel from its own path", () => {
    renderAt("/settings/workspace");
    expect(screen.getByText("Family")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /members/i })).toHaveAttribute("href", "/members");
  });
});
