import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
vi.mock("../../api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("../../api/client")>();
  return { ...original, api: { ...original.api, post: (...a: unknown[]) => post(...a) } };
});

import { ScenarioPanel } from "./ScenarioPanel";

const RESULT = {
  currency: "USD",
  baseline: {
    safe_to_spend_minor: 50_000,
    first_negative_on: null,
    lowest_balance_minor: 50_000,
    fi_years: 21.0,
    fi_number_minor: 90_000_000,
  },
  scenario: {
    safe_to_spend_minor: 12_000,
    first_negative_on: "2026-08-28",
    lowest_balance_minor: 12_000,
    fi_years: 24.5,
    fi_number_minor: 105_000_000,
  },
  notes: ["The change is applied evenly across the projection window."],
};

beforeEach(() => {
  vi.clearAllMocks();
  post.mockResolvedValue(RESULT);
});

describe("ScenarioPanel", () => {
  it("converts whole-unit inputs to minor units for the API", async () => {
    // People think in "5,000 more", the API speaks cents. Sending 5000 raw
    // would model a scenario a hundred times smaller than the one typed.
    render(<ScenarioPanel />);
    fireEvent.change(screen.getByLabelText(/income change/i), { target: { value: "5000" } });
    fireEvent.change(screen.getByLabelText(/spending change/i), { target: { value: "-2000" } });
    fireEvent.click(screen.getByRole("button", { name: /preview/i }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0][1]).toEqual({
      monthly_income_delta_minor: 500_000,
      monthly_expense_delta_minor: -200_000,
    });
  });

  it("shows before and after side by side", async () => {
    render(<ScenarioPanel />);
    fireEvent.click(screen.getByRole("button", { name: /preview/i }));

    expect(await screen.findByText("$500.00")).toBeInTheDocument();
    expect(screen.getByText("$120.00")).toBeInTheDocument();
    expect(screen.getByText("21 yrs")).toBeInTheDocument();
    expect(screen.getByText("24.5 yrs")).toBeInTheDocument();
  });

  it("a crossing that only exists in the scenario is named with its date", async () => {
    render(<ScenarioPanel />);
    fireEvent.click(screen.getByRole("button", { name: /preview/i }));

    expect(await screen.findByText(/never in this window/i)).toBeInTheDocument();
    expect(screen.getByText(/28 Aug|Aug 28/)).toBeInTheDocument();
    expect(screen.getByText(/2026/)).toBeInTheDocument();
  });

  it("runs nothing until asked", () => {
    // A projection that fires on every keystroke turns typing "1000" into
    // four scenarios, three of them nonsense.
    render(<ScenarioPanel />);
    fireEvent.change(screen.getByLabelText(/income change/i), { target: { value: "500" } });
    expect(post).not.toHaveBeenCalled();
  });
});
