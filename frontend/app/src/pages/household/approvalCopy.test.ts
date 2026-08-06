import { describe, expect, it } from "vitest";
import { COPY, timeLeft } from "./ApprovalsCard";

/* The wording is the feature here, not decoration.
 *
 * A REQUESTED approval is a decision — the money has not moved. A FLAGGED one
 * is a review — it already has. If the interface uses the same words for both,
 * it claims to have blocked a purchase it merely noticed, which is a claim the
 * product cannot support. These tests hold that line. */
describe("approval copy", () => {
  it("tells the user a request has not been spent yet", () => {
    expect(COPY.requested.note).toMatch(/not spent/i);
  });

  it("tells the user a flag already went out, and that reviewing does not undo it", () => {
    expect(COPY.flagged.note).toMatch(/already been paid/i);
    expect(COPY.flagged.note).toMatch(/does not undo/i);
  });

  it("never offers to 'approve' something that already happened", () => {
    // "Approve" implies permission over a future event. A flag gets
    // "Looks fine", which is a review, not a authorisation.
    expect(COPY.flagged.yes.toLowerCase()).not.toContain("approve");
    expect(COPY.requested.yes.toLowerCase()).toContain("approve");
  });

  it("declines without blame in either mode", () => {
    for (const kind of ["requested", "flagged"] as const) {
      const no = COPY[kind].no.toLowerCase();
      for (const loaded of ["reject", "deny", "refuse", "wrong"]) {
        expect(no).not.toContain(loaded);
      }
    }
  });
});

describe("timeLeft", () => {
  it("is null when a request never expires", () => {
    expect(timeLeft(null)).toBeNull();
  });

  it("counts down in hours inside a day", () => {
    const inFive = new Date(Date.now() + 5 * 3_600_000).toISOString();
    expect(timeLeft(inFive)).toBe("5h left to answer");
  });

  it("switches to days beyond one", () => {
    const inThreeDays = new Date(Date.now() + 72 * 3_600_000).toISOString();
    expect(timeLeft(inThreeDays)).toBe("3d left to answer");
  });

  it("says expired rather than showing a negative countdown", () => {
    const past = new Date(Date.now() - 3_600_000).toISOString();
    expect(timeLeft(past)).toBe("expired");
  });
});
