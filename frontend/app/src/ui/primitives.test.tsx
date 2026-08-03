import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Banner, Button } from ".";

describe("Button", () => {
  it("renders its label and fires onClick", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Save</Button>);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("defaults to type=button (never an accidental form submit)", () => {
    render(<Button>Go</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "button");
  });

  it("applies the variant class", () => {
    render(<Button variant="danger">Delete</Button>);
    expect(screen.getByRole("button")).toHaveClass("lf-btn--danger");
  });

  it("is disabled and busy while loading, and swallows clicks", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Saving
      </Button>,
    );
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-busy", "true");
    expect(btn).toHaveClass("is-loading");
    await user.click(btn);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("honors an explicit disabled prop", () => {
    render(<Button disabled>Nope</Button>);
    expect(screen.getByRole("button")).toBeDisabled();
  });
});

describe("Banner", () => {
  it("uses role=alert for danger and role=status otherwise", () => {
    const { rerender } = render(<Banner tone="danger">Boom</Banner>);
    expect(screen.getByRole("alert")).toHaveTextContent("Boom");

    rerender(<Banner tone="success">Saved</Banner>);
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
  });

  it("renders a dismiss control that calls onDismiss", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(
      <Banner tone="info" onDismiss={onDismiss}>
        Heads up
      </Banner>,
    );
    await user.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("has no dismiss control when onDismiss is omitted", () => {
    render(<Banner tone="warning">Just so you know</Banner>);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
