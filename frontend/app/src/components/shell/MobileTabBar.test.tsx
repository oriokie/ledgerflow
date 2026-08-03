import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { MobileTabBar } from "./MobileTabBar";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <MobileTabBar />
    </MemoryRouter>,
  );
}

describe("MobileTabBar", () => {
  it("renders the five shortcut destinations as links", () => {
    renderAt("/");
    const nav = screen.getByRole("navigation", { name: /primary shortcuts/i });
    const links = nav.querySelectorAll("a");
    expect(links).toHaveLength(5);
    expect(screen.getByRole("link", { name: /transactions/i })).toHaveAttribute("href", "/transactions");
    expect(screen.getByRole("link", { name: /bills/i })).toHaveAttribute("href", "/bills");
  });

  it("marks the current destination for assistive tech and styling", () => {
    renderAt("/budgets");
    expect(screen.getByRole("link", { name: /budgets/i })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /overview/i })).not.toHaveAttribute("aria-current");
  });
});
