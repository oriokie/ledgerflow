import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Recommendation } from "../../api/types";
import { GuidanceCard } from "./GuidanceCard";

const navigate = vi.fn();
vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}));

function renderCard(rec: Recommendation) {
  return render(
    <MemoryRouter>
      <GuidanceCard rec={rec} />
    </MemoryRouter>,
  );
}

describe("GuidanceCard", () => {
  it("shows the guidance and routes its action to the right place", () => {
    navigate.mockClear();
    renderCard({
      kind: "budget_rebalance",
      title: "Groceries is over by 62.00",
      body: "Dining out has room to cover it.",
      severity: "attention",
      action: { action: "budget_rebalance" },
    });
    expect(screen.getByText("Groceries is over by 62.00")).toBeInTheDocument();
    expect(screen.getByText(/based on your budgets/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open budgets" }));
    expect(navigate).toHaveBeenCalledWith("/budgets");
  });

  it("shows no action for positive good-news guidance", () => {
    renderCard({
      kind: "savings_opportunity",
      title: "You're saving 22% of income",
      body: "Ahead of the 15% guideline. Keep it up.",
      severity: "good",
      action: {},
    });
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
