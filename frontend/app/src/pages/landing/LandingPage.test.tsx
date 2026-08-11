import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const usePlans = vi.fn();
vi.mock("../../hooks/useBilling", () => ({ usePlans: () => usePlans() }));

import { LandingPage } from "../LandingPage";

const plan = (over: Record<string, unknown> = {}) => ({
  id: "p1",
  tier: "plus",
  name: "Plus",
  description: "Planning tools.",
  price_minor: 700,
  currency: "USD",
  interval: "monthly",
  max_members: 2,
  max_accounts: 25,
  ai_insights: true,
  features: [],
  ...over,
});

function renderPage() {
  return render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>,
  );
}

describe("landing page", () => {
  it("prices from the live catalogue, not from copy", () => {
    // Hardcoding prices here would let the page advertise something a visitor
    // is not actually charged. It reads the same public endpoint the billing
    // screen does, so the two cannot disagree.
    usePlans.mockReturnValue({ data: [plan(), plan({ id: "p2", tier: "free", name: "Free", price_minor: 0 })] });
    renderPage();
    expect(screen.getByText("$7.00")).toBeInTheDocument();
    expect(screen.getByText("Free", { selector: ".lf-price-amount" })).toBeInTheDocument();
  });

  it("shows only monthly plans, so a tier appears once", () => {
    usePlans.mockReturnValue({
      data: [plan(), plan({ id: "p2", interval: "yearly", price_minor: 7000, name: "Plus (annual)" })],
    });
    renderPage();
    expect(screen.getAllByRole("heading", { name: "Plus", level: 3 })).toHaveLength(1);
  });

  it("degrades to a message rather than an empty grid while plans load", () => {
    usePlans.mockReturnValue({ data: undefined });
    renderPage();
    expect(screen.getByText(/loading the current plans/i)).toBeInTheDocument();
  });

  it("uses a theme-paired hero from the editorial illustration set", () => {
    usePlans.mockReturnValue({ data: [] });
    const { container } = renderPage();
    expect(container.querySelector(".lf-hero-visual-image--light")).toHaveAttribute(
      "src",
      "/illustrations/editorial/landing-hero.webp",
    );
    expect(container.querySelector(".lf-hero-visual-image--dark")).toHaveAttribute(
      "src",
      "/illustrations/editorial/landing-hero-dark.webp",
    );
  });

  it("has exactly one h1", () => {
    usePlans.mockReturnValue({ data: [] });
    renderPage();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("quotes no figures anywhere in the interface preview", () => {
    // Any number on a finance landing page is either somebody's real data or
    // invented data dressed as real. The preview is deliberately abstract.
    usePlans.mockReturnValue({ data: [] });
    const { container } = renderPage();
    const preview = container.querySelector(".lf-preview");
    expect(preview).not.toBeNull();
    expect(preview?.textContent?.trim()).toBe("");
  });
});
