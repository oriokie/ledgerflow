import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { DebtStress } from "../../api/types";
import { DebtStressCard } from "./DebtStressCard";

const STRESS: DebtStress = {
  score: 62,
  band: "moderate",
  coverage: 1.0,
  is_provisional: false,
  missed_payment_penalty: 0,
  weakest: "interest_burden",
  components: [
    {
      key: "interest_burden",
      label: "Interest burden",
      score: 30,
      weight: 0.2,
      value: 55.0,
      detail: "About 55% of your minimum payments goes to interest rather than reducing the balance.",
    },
    {
      key: "debt_to_income",
      label: "Debt to income",
      score: 80,
      weight: 0.25,
      value: 1.2,
      detail: "You owe about 1.2× your annual income.",
    },
  ],
  method: "Each component is scored 0–100 where higher is better, then combined by weight.",
  currency: "USD",
};

function renderCard(overrides: Partial<DebtStress> = {}) {
  return render(<DebtStressCard stress={{ ...STRESS, ...overrides }} />);
}

describe("DebtStressCard", () => {
  it("shows the score and its band", () => {
    renderCard();
    expect(screen.getByText("62")).toBeInTheDocument();
    expect(screen.getByText("Moderate")).toBeInTheDocument();
  });

  it("exposes the score to assistive tech, not just as a dial", () => {
    renderCard();
    expect(screen.getByRole("img", { name: /62 out of 100/i })).toBeInTheDocument();
  });

  it("keeps the derivation one click away rather than hidden", () => {
    // A composite score nobody can interrogate is one they over-trust or ignore.
    renderCard();
    expect(screen.queryByText(/interest burden/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /how is this worked out/i })).toBeInTheDocument();
  });

  it("leads with the weakest component when expanded", async () => {
    const user = userEvent.setup();
    renderCard();
    await user.click(screen.getByRole("button", { name: /how is this worked out/i }));

    // Where an improvement moves the total most — the actionable part.
    const labels = screen.getAllByText(/interest burden|debt to income/i);
    expect(labels[0]).toHaveTextContent(/interest burden/i);
    expect(screen.getByText(/55% of your minimum payments/i)).toBeInTheDocument();
  });

  it("states when the score is based on partial data", () => {
    // Better than presenting an incomplete score as complete.
    renderCard({ is_provisional: true, coverage: 0.45 });
    expect(screen.getByText(/45% of the usual inputs/i)).toBeInTheDocument();
  });

  it("shows no provisional note when everything was measurable", () => {
    renderCard({ is_provisional: false });
    expect(screen.queryByText(/usual inputs/i)).not.toBeInTheDocument();
  });

  it("names a missed-payment penalty rather than burying it in the total", async () => {
    const user = userEvent.setup();
    renderCard({ missed_payment_penalty: 16 });
    await user.click(screen.getByRole("button", { name: /how is this worked out/i }));
    expect(screen.getByText(/−16 for missed payments/i)).toBeInTheDocument();
  });

  it("colours the dial by band without relying on colour alone", () => {
    const { container } = renderCard({ band: "critical", score: 18 });
    expect(container.querySelector('[data-band="critical"]')).toBeInTheDocument();
    // The band is always stated in words too.
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });
});
