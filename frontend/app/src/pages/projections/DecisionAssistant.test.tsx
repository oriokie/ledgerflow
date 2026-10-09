import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { advisorApi } from "../../api/projections";
import type { DecisionResult, Position, QuestionMeta } from "../../api/projections";
import { DecisionAssistant } from "./DecisionAssistant";

const downloadFilePost = vi.fn().mockResolvedValue(undefined);
vi.mock("../../lib/download", () => ({
  downloadFilePost: (...args: unknown[]) => downloadFilePost(...args),
}));

vi.mock("../../api/projections", () => ({
  advisorApi: {
    questions: vi.fn(),
    kenyaRates: vi.fn(),
    ask: vi.fn(),
    share: vi.fn(),
  },
}));

const POSITION: Position = {
  currency: "KES",
  as_of: "2026-10-09",
  liquid_minor: 800_000,
  investment_minor: 0,
  other_assets_minor: 0,
  monthly_net_income_minor: 200_000,
  monthly_expenses_minor: 80_000,
  net_worth_minor: 800_000,
  debts: [],
};

const QUESTIONS: QuestionMeta[] = [
  {
    slug: "afford-mortgage",
    question: "Can I afford this mortgage?",
    fields: [
      { name: "property_price_minor", required: true, type: "integer" },
      { name: "deposit_minor", required: true, type: "integer" },
      { name: "annual_rate", required: true, type: "decimal" },
    ],
  },
];

const RESULT: DecisionResult = {
  question: "Can I afford this mortgage?",
  verdict: "yes",
  headline: "The payment fits.",
  confidence: "measured",
  because: [],
  costs: [],
  risks: [],
  alternatives: [],
  assumptions: ["Rate stays put."],
  explanation: { paragraphs: ["It fits."], llm_used: false, rejected_reason: "" },
  currency: "KES",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(advisorApi.questions).mockResolvedValue({ results: QUESTIONS });
  vi.mocked(advisorApi.kenyaRates).mockResolvedValue({ as_of: "2026-01-01", source: "test" });
  vi.mocked(advisorApi.ask).mockResolvedValue(RESULT);
  vi.mocked(advisorApi.share).mockResolvedValue({
    url: "https://app.example.com/share/decision?token=abc",
    expires_at: "2026-10-16T00:00:00Z",
  });
});

async function fillMortgageForm() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Answer this" })).toBeEnabled());
  // Defaults land in an effect after the form enables; filling sooner is overwritten.
  await waitFor(() => expect(screen.getByLabelText(/deposit/i)).toHaveValue(5600));
  fireEvent.change(screen.getByLabelText(/property price/i), { target: { value: "200000" } });
  fireEvent.change(screen.getByLabelText(/deposit/i), { target: { value: "50000" } });
  fireEvent.change(screen.getByLabelText(/annual rate/i), { target: { value: "9" } });
}

describe("DecisionAssistant take-home actions", () => {
  it("offers PDF, Excel and a share link after an answer", async () => {
    render(<DecisionAssistant position={POSITION} />);
    await fillMortgageForm();
    fireEvent.click(screen.getByRole("button", { name: "Answer this" }));

    await waitFor(() => expect(screen.getByText("The payment fits.")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    await waitFor(() =>
      expect(downloadFilePost).toHaveBeenCalledWith(
        "/projections/questions/afford-mortgage/export.pdf",
        "ledgerflow-afford-mortgage.pdf",
        expect.objectContaining({ property_price_minor: 20_000_000 }),
      ),
    );
  });

  it("resets the form and clears the last answer", async () => {
    render(<DecisionAssistant position={POSITION} />);
    await fillMortgageForm();
    fireEvent.click(screen.getByRole("button", { name: "Answer this" }));
    await waitFor(() => expect(screen.getByText("The payment fits.")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Reset inputs" }));
    expect(screen.queryByText("The payment fits.")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/property price/i)).toHaveValue(null);
  });
});
