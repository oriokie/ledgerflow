import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ isAuthenticated: false, login: vi.fn() }),
}));

import { RegisterPage } from "./RegisterPage";

describe("RegisterPage legal links", () => {
  it("exposes Terms and Privacy as standalone legal targets", () => {
    render(
      <MemoryRouter>
        <RegisterPage />
      </MemoryRouter>,
    );
    const nav = screen.getByRole("navigation", { name: "Legal" });
    expect(nav.querySelector('a[href="/terms"]')).toHaveTextContent("Terms");
    expect(nav.querySelector('a[href="/privacy"]')).toHaveTextContent("Privacy Policy");
  });
});
