import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { authApi } from "../api/auth";
import { ResetPasswordPage } from "./ResetPasswordPage";

vi.mock("../api/auth", () => ({
  authApi: {
    confirmPasswordReset: vi.fn(),
  },
}));

beforeEach(() => vi.clearAllMocks());

describe("ResetPasswordPage", () => {
  it("rejects a missing token with a recovery path", () => {
    render(
      <MemoryRouter initialEntries={["/reset-password"]}>
        <Routes>
          <Route path="/reset-password" element={<ResetPasswordPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText(/link expired or invalid/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /request a new link/i })).toHaveAttribute("href", "/forgot-password");
  });

  it("submits the new password with the token from the URL, then routes to login", async () => {
    vi.mocked(authApi.confirmPasswordReset).mockResolvedValue({ detail: "done" });
    render(
      <MemoryRouter initialEntries={["/reset-password?token=abc123"]}>
        <Routes>
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/login" element={<div>Login screen</div>} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText(/new password/i), { target: { value: "BrandNewPass9$x" } });
    fireEvent.click(screen.getByRole("button", { name: /reset password/i }));

    await waitFor(() => expect(screen.getByText("Login screen")).toBeInTheDocument());
    expect(authApi.confirmPasswordReset).toHaveBeenCalledWith("abc123", "BrandNewPass9$x");
  });
});
