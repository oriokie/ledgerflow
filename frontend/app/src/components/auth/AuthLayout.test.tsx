import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AuthDivider, AuthLayout } from "./AuthLayout";

describe("AuthLayout", () => {
  it("shows the brand and its children", () => {
    render(
      <AuthLayout>
        <h1>Log in</h1>
      </AuthLayout>,
    );
    expect(screen.getAllByText("LedgerFlow").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Log in" })).toBeInTheDocument();
  });

  it("renders a footer when provided", () => {
    render(<AuthLayout footer={<span>Create an account</span>}>x</AuthLayout>);
    expect(screen.getByText("Create an account")).toBeInTheDocument();
  });

  it("omits the footer element when not provided", () => {
    const { container } = render(<AuthLayout>x</AuthLayout>);
    // the footer <p> carries these utility classes; ensure none rendered
    expect(container.querySelector("p.lf-text-secondary")).toBeNull();
  });

  it("applies a custom max width to the card", () => {
    const { container } = render(<AuthLayout maxWidth={440}>x</AuthLayout>);
    const card = container.querySelector(".lf-auth-card") as HTMLElement;
    expect(card.style.maxWidth).toBe("440px");
  });
});

describe("AuthDivider", () => {
  it("renders a separator with a default label", () => {
    render(<AuthDivider />);
    expect(screen.getByRole("separator")).toHaveTextContent("or");
  });
});
