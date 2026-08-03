import { describe, expect, it } from "vitest";
import { bulkMessage } from "./bulk";

describe("bulkMessage", () => {
  it("celebrates full success", () => {
    expect(bulkMessage({ total: 5, failed: 0 }, "Categorized")).toEqual({
      tone: "success",
      text: "Categorized 5 transactions.",
    });
  });

  it("uses the singular for one transaction", () => {
    expect(bulkMessage({ total: 1, failed: 0 }, "Voided").text).toBe("Voided 1 transaction.");
  });

  it("warns on partial failure with counts", () => {
    expect(bulkMessage({ total: 5, failed: 2 }, "Categorized")).toEqual({
      tone: "warning",
      text: "Categorized 3 of 5 transactions — 2 failed.",
    });
  });

  it("reports total failure as an error", () => {
    expect(bulkMessage({ total: 3, failed: 3 }, "Voided")).toEqual({
      tone: "danger",
      text: "None of the 3 transactions could be voided.",
    });
  });
});
