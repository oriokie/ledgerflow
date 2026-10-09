import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ContactPage } from "./LegalPage";

describe("ContactPage", () => {
  it("offers an email address as the support channel", () => {
    render(
      <MemoryRouter>
        <ContactPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Contact" })).toBeInTheDocument();
    const mail = screen.getByRole("link", { name: "support@ledgerflow.app" });
    expect(mail).toHaveAttribute("href", "mailto:support@ledgerflow.app");
  });
});
