import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Subscription } from "../../api/types";
import { PlanUsage } from "./PlanUsage";

function sub(over: Partial<Subscription> = {}): Subscription {
  return {
    id: "s1",
    plan: {
      id: "p1",
      tier: "free",
      name: "Free",
      description: "",
      price_minor: 0,
      currency: "USD",
      interval: "monthly",
      max_members: 1,
      max_accounts: 3,
      ai_insights: false,
      features: [],
    },
    status: "active",
    is_current: true,
    current_period_start: null,
    current_period_end: null,
    cancel_at_period_end: false,
    canceled_at: null,
    trial_end: null,
    provider: "",
    ...over,
  } as Subscription;
}

describe("PlanUsage", () => {
  it("shows accounts/members used against plan limits", () => {
    render(<PlanUsage subscription={sub()} accountsUsed={2} membersUsed={1} />);
    expect(screen.getByText("2 of 3 used")).toBeInTheDocument();
    expect(screen.getByText("1 of 1 used")).toBeInTheDocument();
  });

  it("renders nothing for a non-metered (canceled) subscription", () => {
    const { container } = render(
      <PlanUsage subscription={sub({ status: "canceled" })} accountsUsed={2} membersUsed={1} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
