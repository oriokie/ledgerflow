import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PasswordInput } from "./PasswordInput";

describe("PasswordInput", () => {
  it("associates the label with the input", () => {
    render(<PasswordInput label="Password" />);
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("masks input by default", () => {
    render(<PasswordInput label="Password" />);
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
  });

  it("reveals and re-hides via the accessible toggle", async () => {
    const user = userEvent.setup();
    render(<PasswordInput label="Password" />);
    const input = screen.getByLabelText("Password");

    const show = screen.getByRole("button", { name: "Show password" });
    expect(show).toHaveAttribute("aria-pressed", "false");

    await user.click(show);
    expect(input).toHaveAttribute("type", "text");

    const hide = screen.getByRole("button", { name: "Hide password" });
    expect(hide).toHaveAttribute("aria-pressed", "true");

    await user.click(hide);
    expect(input).toHaveAttribute("type", "password");
  });

  it("surfaces an error message and marks the field invalid", () => {
    render(<PasswordInput label="Password" error="Too short" />);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Too short");
  });

  it("forwards typing to the underlying input", async () => {
    const user = userEvent.setup();
    render(<PasswordInput label="Password" />);
    const input = screen.getByLabelText("Password");
    await user.type(input, "hunter2hunter2");
    expect(input).toHaveValue("hunter2hunter2");
  });
});
