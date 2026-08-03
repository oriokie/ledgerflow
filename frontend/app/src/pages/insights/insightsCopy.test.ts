import { describe, expect, it } from "vitest";
import type { Anomaly, HealthScore, Recommendation } from "../../api/types";
import {
  anomalyView,
  bandTone,
  confidenceLabel,
  greeting,
  healthSummary,
  recommendationBasis,
  recommendationCta,
  recommendationTone,
} from "./insightsCopy";

function health(over: Partial<HealthScore> = {}): HealthScore {
  return {
    score: 72,
    band: "good",
    provider: "x",
    version: "1",
    components: [
      { name: "Savings rate", score: 90, weight: 0.3, detail: "Keeping 22% of income." },
      { name: "Emergency fund", score: 40, weight: 0.3, detail: "2.4 months of essentials covered." },
    ],
    ...over,
  };
}

function rec(over: Partial<Recommendation> = {}): Recommendation {
  return { kind: "savings_opportunity", title: "t", body: "b", severity: "good", action: {}, ...over };
}

describe("bandTone / greeting", () => {
  it("maps bands to tones", () => {
    expect(bandTone("excellent")).toBe("good");
    expect(bandTone("good")).toBe("good");
    expect(bandTone("fair")).toBe("soon");
    expect(bandTone("needs attention")).toBe("attention");
  });

  it("greets differently by how much needs action", () => {
    expect(greeting(health(), 0).subtitle).toMatch(/nothing needs action/i);
    expect(greeting(health(), 1).subtitle).toMatch(/one suggestion/i);
    expect(greeting(health(), 3).subtitle).toMatch(/3 suggestions/i);
  });
});

describe("healthSummary", () => {
  it("picks the top strength and a lagging watch-out", () => {
    const s = healthSummary(health())!;
    expect(s.strength?.name).toBe("Savings rate");
    expect(s.watch?.name).toBe("Emergency fund"); // 40 < 60 threshold
    expect(s.tone).toBe("good");
    expect(s.score).toBe(72);
  });

  it("omits the watch-out when nothing lags", () => {
    const s = healthSummary(
      health({ components: [{ name: "Savings rate", score: 88, weight: 1, detail: "d" }] }),
    )!;
    expect(s.watch).toBeNull();
  });
});

describe("recommendations", () => {
  it("routes each action to a concrete next step, except good news", () => {
    expect(recommendationCta(rec({ kind: "budget_rebalance", action: { action: "budget_rebalance" } }))).toEqual({
      label: "Open budgets",
      to: "/budgets",
    });
    // The backend used to emit "schedule_transfer" here, proposing a
    // from-account/to-account transfer that Bill has no model support for
    // and that this router never actually read anyway — it always just
    // linked to /bills regardless. Fixed to emit "bill_upcoming" with a real
    // bill_id instead (see apps/intelligence/providers/recommend.py); this
    // test now matches what the backend genuinely sends.
    expect(recommendationCta(rec({ kind: "bill_upcoming", action: { action: "bill_upcoming", bill_id: "b1" } }))).toEqual({
      label: "Review bills",
      to: "/bills",
    });
    expect(recommendationCta(rec({ kind: "subscription_review", action: {} }))).toEqual({
      label: "Review subscriptions",
      to: "/recurring",
    });
    expect(recommendationCta(rec({ kind: "savings_opportunity", action: {} }))).toBeNull();
  });

  it("tones by severity and states an honest basis", () => {
    expect(recommendationTone("attention")).toBe("attention");
    expect(recommendationTone("good")).toBe("good");
    expect(recommendationBasis(rec({ kind: "bill_upcoming" }))).toMatch(/upcoming bills/i);
    expect(recommendationBasis(rec({ kind: "savings_opportunity" }))).toMatch(/income and spending/i);
  });
});

describe("anomalyView / confidenceLabel", () => {
  const anomaly = (over: Partial<Anomaly>): Anomaly => ({
    transaction_id: "t1",
    kind: "amount_spike",
    severity: 0.5,
    explanation: "e",
    ...over,
  });

  it("gives a plain headline and escalates tone by severity", () => {
    expect(anomalyView(anomaly({ kind: "amount_spike", severity: 0.5 }))).toEqual({
      headline: "A charge that's higher than usual",
      tone: "soon",
    });
    expect(anomalyView(anomaly({ kind: "duplicate", severity: 0.8 })).tone).toBe("attention");
  });

  it("turns confidence into words", () => {
    expect(confidenceLabel(0.3)).toBe("It's a guess");
    expect(confidenceLabel(0.6)).toBe("Fairly sure");
    expect(confidenceLabel(0.95)).toBe("Very sure");
  });
});
