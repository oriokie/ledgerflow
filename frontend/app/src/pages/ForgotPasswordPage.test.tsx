import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { authApi } from "../api/auth";
import { ForgotPasswordPage } from "./ForgotPasswordPage";

vi.mock("../api/auth", () => ({
  authApi: {
    requestPasswordReset: vi.fn(),
  },
}));

beforeEach(() => vi.clearAllMocks());

describe("ForgotPasswordPage", () => {
  it("confirms a link was sent without revealing whether the email exists", async () => {
    vi.mocked(authApi.requestPasswordReset).mockResolvedValue({ detail: "ok" });
    render(
      <MemoryRouter>
        <ForgotPasswordPage />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "sam@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => expect(screen.getByText(/check your email/i)).toBeInTheDocument());
    expect(authApi.requestPasswordReset).toHaveBeenCalledWith("sam@example.com");
    // Neutral copy — never confirms/denies the address.
    expect(screen.getByText(/if that address is registered/i)).toBeInTheDocument();
  });
});
