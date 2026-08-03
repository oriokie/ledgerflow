import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

// The four tab bodies are full pages with their own data hooks; this suite is
// about the hub's contract — which tab, from where, and what the URL says.
vi.mock("./BudgetsPage", () => ({ BudgetsPage: () => <p>budgets body</p> }));
vi.mock("./BillsPage", () => ({ BillsPage: () => <p>bills body</p> }));
vi.mock("./RecurringPage", () => ({ RecurringPage: () => <p>recurring body</p> }));
vi.mock("./CashflowPage", () => ({ CashflowPage: () => <p>cashflow body</p> }));

import { PlanPage } from "./PlanPage";

function Probe() {
  const { search } = useLocation();
  return <span data-testid="qs">{search}</span>;
}

function renderAt(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route
          path="/plan"
          element={
            <>
              <PlanPage />
              <Probe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("PlanPage", () => {
  it("opens on Budgets when no tab is named", () => {
    renderAt("/plan");
    expect(screen.getByText("budgets body")).toBeInTheDocument();
  });

  it("opens on the tab a redirect asked for", () => {
    // This is what makes `/bills → /plan?tab=bills` a redirect rather than a
    // relocation: the user arrives where they were going.
    renderAt("/plan?tab=bills");
    expect(screen.getByText("bills body")).toBeInTheDocument();
    expect(screen.queryByText("budgets body")).not.toBeInTheDocument();
  });

  it("falls back rather than rendering nothing for a bad tab", () => {
    renderAt("/plan?tab=nonsense");
    expect(screen.getByText("budgets body")).toBeInTheDocument();
  });

  it("puts the tab in the URL so it can be linked and bookmarked", async () => {
    const user = userEvent.setup();
    renderAt("/plan");
    await user.click(screen.getByRole("tab", { name: "Cash flow" }));
    expect(screen.getByText("cashflow body")).toBeInTheDocument();
    expect(screen.getByTestId("qs")).toHaveTextContent("tab=cashflow");
  });

  it("keeps the default tab out of the URL", async () => {
    // `/plan` and `/plan?tab=budgets` are the same place; only one of them
    // should be the canonical URL.
    const user = userEvent.setup();
    renderAt("/plan?tab=bills");
    await user.click(screen.getByRole("tab", { name: "Budgets" }));
    expect(screen.getByTestId("qs")).toHaveTextContent("");
  });

  it("exposes the tabs as a real tablist", () => {
    renderAt("/plan?tab=recurring");
    expect(screen.getByRole("tablist", { name: "Plan sections" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Recurring" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Bills" })).toHaveAttribute("aria-selected", "false");
  });

  it("owns the page title so the embedded pages don't duplicate it", () => {
    renderAt("/plan");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Plan");
  });
});
