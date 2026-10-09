import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { advisorApi } from "../api/projections";
import type { DecisionResult } from "../api/projections";
import { ShareDecisionPage } from "./ShareDecisionPage";

vi.mock("../api/projections", () => ({
  advisorApi: {
    shared: vi.fn(),
  },
}));

const RESULT: DecisionResult = {
  question: "Can I afford this mortgage?",
  verdict: "yes_with_care",
  headline: "Affordable if the rate holds.",
  confidence: "mixed",
  because: [{ label: "Payment", text: "Fits the budget.", amount_minor: 50_000, months: null, percent: null }],
  costs: [],
  risks: [],
  alternatives: [],
  assumptions: ["Rate stays at 9%."],
  explanation: { paragraphs: ["The payment fits."], llm_used: false, rejected_reason: "" },
  currency: "KES",
};

beforeEach(() => vi.clearAllMocks());

describe("ShareDecisionPage", () => {
  it("renders the frozen snapshot from the token", async () => {
    vi.mocked(advisorApi.shared).mockResolvedValue(RESULT);
    render(
      <MemoryRouter initialEntries={["/share/decision?token=abc"]}>
        <ShareDecisionPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("Affordable if the rate holds.")).toBeInTheDocument());
    expect(advisorApi.shared).toHaveBeenCalledWith("abc");
    expect(screen.getByRole("button", { name: "Download PDF" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download Excel" })).toBeInTheDocument();
  });

  it("says so when the link is missing", () => {
    render(
      <MemoryRouter initialEntries={["/share/decision"]}>
        <ShareDecisionPage />
      </MemoryRouter>,
    );
    expect(screen.getByText(/missing or malformed/i)).toBeInTheDocument();
  });
});
