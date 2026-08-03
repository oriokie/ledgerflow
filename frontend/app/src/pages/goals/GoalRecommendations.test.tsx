import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { GoalRecommendation } from "../../api/types";
import { GoalRecommendations } from "./GoalRecommendations";

const REC: GoalRecommendation = {
  kind: "emergency_fund",
  title: "Build an emergency fund",
  rationale: "Your spending averages about 2,100 USD a month. 3 months of cover would be 6,300 USD.",
  suggested_target_minor: 630_000,
  suggested_monthly_minor: 52_500,
  currency: "USD",
  priority: 1,
};

describe("GoalRecommendations", () => {
  it("renders nothing at all when there are no suggestions", () => {
    // The engine returns an empty list rather than filler; a "no suggestions"
    // panel would reintroduce the noise it avoids.
    const { container } = render(<GoalRecommendations recommendations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("leads with the rationale, so the number can be checked", () => {
    render(<GoalRecommendations recommendations={[REC]} />);
    expect(screen.getByText(/your spending averages about 2,100 usd a month/i)).toBeInTheDocument();
  });

  it("shows the suggested target and monthly pace", () => {
    render(<GoalRecommendations recommendations={[REC]} />);
    expect(screen.getByText("Suggested target")).toBeInTheDocument();
    expect(screen.getByText("Monthly")).toBeInTheDocument();
  });

  it("omits the monthly figure when the engine couldn't derive one", () => {
    render(<GoalRecommendations recommendations={[{ ...REC, suggested_monthly_minor: null }]} />);
    expect(screen.queryByText("Monthly")).not.toBeInTheDocument();
    expect(screen.getByText("Suggested target")).toBeInTheDocument();
  });

  it("hands the whole recommendation back on accept", async () => {
    const user = userEvent.setup();
    const onAccept = vi.fn();
    render(<GoalRecommendations recommendations={[REC]} onAccept={onAccept} />);
    await user.click(screen.getByRole("button", { name: /set this up/i }));
    expect(onAccept).toHaveBeenCalledWith(REC);
  });

  it("renders one card per suggestion", () => {
    render(
      <GoalRecommendations
        recommendations={[REC, { ...REC, kind: "debt_payoff", title: "Clear your card" }]}
      />,
    );
    expect(screen.getByText("Build an emergency fund")).toBeInTheDocument();
    expect(screen.getByText("Clear your card")).toBeInTheDocument();
  });
});
