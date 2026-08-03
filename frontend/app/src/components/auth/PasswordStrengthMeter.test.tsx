import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PasswordStrengthMeter } from "./PasswordStrengthMeter";

/** The meter exposes its level through an aria-label ("Password strength: X"),
 * so we assert behavior the way a screen-reader user would perceive it. */
function levelOf(password: string): string | null {
  const { unmount } = render(<PasswordStrengthMeter password={password} />);
  const el = screen.queryByRole("img");
  const label = el?.getAttribute("aria-label") ?? null;
  unmount();
  return label;
}

describe("PasswordStrengthMeter", () => {
  it("renders nothing for an empty password", () => {
    const { container } = render(<PasswordStrengthMeter password="" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("rates anything under 12 characters as Weak", () => {
    expect(levelOf("short")).toBe("Password strength: Weak");
    expect(levelOf("Abc123!x")).toBe("Password strength: Weak"); // 8 chars, still < 12
  });

  it("rates a bare 12-char lowercase string as Fair", () => {
    expect(levelOf("abcdefghijkl")).toBe("Password strength: Fair");
  });

  it("rates a long mixed password as Strong", () => {
    expect(levelOf("Abcdef123!ghij")).toBe("Password strength: Strong");
  });

  it("shows a helpful hint alongside the gauge", () => {
    render(<PasswordStrengthMeter password="short" />);
    expect(screen.getByText(/at least 12 characters/i)).toBeInTheDocument();
  });
});
