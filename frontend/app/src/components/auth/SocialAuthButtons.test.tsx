import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { oauthApi } from "../../api/auth";
import { SocialAuthButtons } from "./SocialAuthButtons";

vi.mock("../../api/auth", () => ({
  oauthApi: { authorize: vi.fn() },
}));

const authorize = vi.mocked(oauthApi.authorize);

describe("SocialAuthButtons", () => {
  const realLocation = window.location;

  beforeEach(() => {
    authorize.mockReset();
    sessionStorage.clear();
    // jsdom won't navigate; swap location for a capturable stub.
    Object.defineProperty(window, "location", { value: { href: "" }, writable: true, configurable: true });
  });

  afterEach(() => {
    Object.defineProperty(window, "location", { value: realLocation, writable: true, configurable: true });
  });

  it("offers Google and Apple", () => {
    render(<SocialAuthButtons />);
    expect(screen.getByRole("button", { name: /continue with google/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /continue with apple/i })).toBeInTheDocument();
  });

  it("starts the PKCE flow and redirects on success", async () => {
    const user = userEvent.setup();
    authorize.mockResolvedValue({ authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?x=1" });
    render(<SocialAuthButtons />);

    await user.click(screen.getByRole("button", { name: /continue with google/i }));

    expect(authorize).toHaveBeenCalledWith("google");
    await waitFor(() => expect(window.location.href).toContain("accounts.google.com"));
    // remembers the provider for the callback page
    expect(sessionStorage.getItem("lf_oauth_provider")).toBe("google");
  });

  it("degrades calmly when a provider isn't configured (400)", async () => {
    const user = userEvent.setup();
    authorize.mockRejectedValue(new ApiError(400, { detail: "not configured" }));
    render(<SocialAuthButtons />);

    await user.click(screen.getByRole("button", { name: /continue with apple/i }));

    expect(await screen.findByText(/apple sign-in isn't available/i)).toBeInTheDocument();
    expect(window.location.href).toBe(""); // no navigation
  });
});
